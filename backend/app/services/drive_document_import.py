"""Import documents directly from the client's Google Drive invoice folders.

Unlike the local-archive importer (which reads files already on the server's
disk), this walks a Drive folder over the Drive API, downloads each file, and
runs it through the very same capture pipeline (supplier/type/pub inference,
local storage, dedup, R2 sync, extraction).

Dedup is on the Drive file id (`gmail_message_id = "drive-<id>"`), so chunked
or repeated runs never re-import or re-download a file that is already in.

Requires the drive.readonly scope — reconnect Google if the existing token
predates it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, GmailConnection, User
from app.services.document_extraction import extract_documents
from app.services.document_registry import upsert_document_record
from app.services.drive_client import (
    download_drive_file,
    find_folder_by_name,
    get_drive_service,
    walk_drive_folder,
)
from app.services.local_document_import import (
    _build_import_filename,
    _infer_date_hint,
    _infer_document_type,
    _infer_pub_hint,
    _infer_reference_hint,
    _infer_supplier,
    _review_reasons,
)
from app.services.local_storage import copy_to_final_storage
from app.services.object_storage import sync_document_to_object_storage

# Only ingest document-like files; skip images/spreadsheets/native Google docs.
_ALLOWED_SUFFIXES = {".pdf"}


@dataclass(slots=True)
class DriveImportResult:
    folder: str
    total_files_in_drive: int = 0
    eligible_files: int = 0
    already_imported: int = 0
    imported_documents: int = 0
    extracted_documents: int = 0
    skipped_files: int = 0
    errors: list[str] = field(default_factory=list)


def _drive_message_id(file_id: str) -> str:
    return f"drive-{file_id}"


async def import_documents_from_drive(
    *,
    user: User,
    db: AsyncSession,
    folder_name: str | None = None,
    folder_id: str | None = None,
    limit: int = 50,
    extract_after_import: bool = False,
) -> DriveImportResult:
    connection = (
        await db.execute(select(GmailConnection).where(GmailConnection.user_id == user.id))
    ).scalar_one_or_none()
    if connection is None:
        raise ValueError("No Google connection found — connect Google on the Tools page first.")

    service = await get_drive_service(connection, db)

    if not folder_id:
        if not folder_name:
            raise ValueError("Provide a Drive folder name or folder id to import from.")
        folder = find_folder_by_name(service, name=folder_name)
        if folder is None:
            raise ValueError(f"No Drive folder named {folder_name!r} was found.")
        folder_id = folder["id"]

    result = DriveImportResult(folder=folder_name or folder_id)

    # Enumerate the tree (metadata only — cheap) and figure out what's new.
    entries = list(walk_drive_folder(service, folder_id))
    result.total_files_in_drive = len(entries)

    eligible: list[tuple[dict, tuple[str, ...]]] = []
    for file_meta, path_parts in entries:
        name = file_meta.get("name", "")
        if Path(name).suffix.lower() not in _ALLOWED_SUFFIXES:
            result.skipped_files += 1
            continue
        eligible.append((file_meta, path_parts))
    result.eligible_files = len(eligible)

    existing_ids = set(
        (
            await db.execute(
                select(Document.gmail_message_id).where(
                    Document.user_id == user.id,
                    Document.gmail_message_id.in_([_drive_message_id(m["id"]) for m, _ in eligible]),
                )
            )
        )
        .scalars()
        .all()
    ) if eligible else set()

    imported_document_ids: list = []
    for file_meta, path_parts in eligible:
        message_id = _drive_message_id(file_meta["id"])
        if message_id in existing_ids:
            result.already_imported += 1
            continue
        if len(imported_document_ids) >= limit:
            break

        relative_path = Path(*path_parts, file_meta["name"]) if path_parts else Path(file_meta["name"])
        supplier = _infer_supplier(relative_path)
        document_type = _infer_document_type(relative_path)
        pub_hint = _infer_pub_hint(relative_path)
        date_hint = _infer_date_hint(relative_path)
        review_reasons = _review_reasons(supplier=supplier, document_type=document_type)

        try:
            payload = download_drive_file(service, file_meta["id"])
        except Exception as exc:  # noqa: BLE001 - report and continue
            result.errors.append(f"{relative_path.as_posix()}: download failed ({exc})")
            continue

        with tempfile.NamedTemporaryFile(suffix=Path(file_meta["name"]).suffix, delete=True) as tmp:
            tmp.write(payload)
            tmp.flush()
            tmp_path = Path(tmp.name)
            stored_path = copy_to_final_storage(
                source_path=tmp_path,
                supplier=supplier,
                document_type=document_type,
                final_name=_build_import_filename(file_path=Path(file_meta["name"]), pub_hint=pub_hint),
                needs_review=bool(review_reasons),
            )

        modified = file_meta.get("modifiedTime")
        received_at = None
        if modified:
            try:
                received_at = datetime.fromisoformat(modified.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                received_at = None

        stored_file = {
            "attachment_name": file_meta["name"],
            "supplier": supplier,
            "document_type": document_type,
            "document_date": date_hint,
            "reference": _infer_reference_hint(relative_path),
            "amount": None,
            "needs_review": bool(review_reasons),
            "review_reasons": review_reasons,
            "saved_path": str(stored_path),
        }
        document = await upsert_document_record(
            db,
            user_id=user.id,
            gmail_message_id=message_id,
            attachment_index=0,
            source_email_sender="google-drive",
            source_email_subject=relative_path.as_posix(),
            source_received_at=received_at or datetime.utcnow(),
            stored_file=stored_file,
        )
        try:
            sync_document_to_object_storage(document=document, source_path=stored_path)
        except Exception:
            pass
        existing_ids.add(message_id)
        if document.id is not None and document.id not in imported_document_ids:
            imported_document_ids.append(document.id)
        result.imported_documents += 1

    if imported_document_ids and extract_after_import:
        summary = await extract_documents(
            user=user,
            db=db,
            limit=len(imported_document_ids),
            document_ids=imported_document_ids,
            force=True,
        )
        result.extracted_documents = summary["extracted"]
    else:
        await db.commit()

    return result
