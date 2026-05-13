from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, GmailConnection
from app.services.drive_client import ensure_drive_path, get_drive_service, move_drive_file
from app.services.drive_paths import drive_path_parts_for_local_path
from app.services.file_namer import build_document_filename
from app.services.local_storage import planned_storage_path, relocate_existing_file


def _serialize_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_amount(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _target_filename(document: Document) -> str:
    return build_document_filename(
        supplier=document.supplier,
        document_type=document.document_type,
        original_filename=document.attachment_name,
        document_date=_serialize_date(document.document_date),
        reference=document.reference,
        amount=_serialize_amount(document.amount),
    )


def _target_local_path(document: Document) -> Path:
    return planned_storage_path(
        supplier=document.supplier,
        document_type=document.document_type,
        final_name=_target_filename(document),
        needs_review=document.needs_review,
    )


def _restore_local_path(current_path: str, previous_path: str) -> None:
    current = Path(current_path)
    previous = Path(previous_path)
    if not current.exists():
        return
    previous.parent.mkdir(parents=True, exist_ok=True)
    current.replace(previous)


async def refile_document_assets(
    *,
    document: Document,
    connection: GmailConnection | None,
    db: AsyncSession,
) -> dict[str, bool]:
    current_local_path = document.local_path
    target_local_path = str(_target_local_path(document))
    if target_local_path == current_local_path:
        return {"local_moved": False, "drive_updated": False}

    if document.drive_file_id and connection is None:
        raise RuntimeError("Gmail is not connected")

    new_local_path = str(
        relocate_existing_file(
            current_path=current_local_path,
            supplier=document.supplier,
            document_type=document.document_type,
            final_name=_target_filename(document),
            needs_review=document.needs_review,
        )
    )

    drive_updated = False
    try:
        if document.drive_file_id:
            service = await get_drive_service(connection, db)
            folder_id, folder_path = ensure_drive_path(
                service,
                drive_path_parts_for_local_path(new_local_path),
            )
            moved = move_drive_file(
                service,
                file_id=document.drive_file_id,
                new_name=Path(new_local_path).name,
                new_parent_id=folder_id,
            )
            document.drive_folder_path = folder_path
            document.drive_web_link = moved.get("webViewLink") or document.drive_web_link
            drive_updated = True
    except Exception:
        if new_local_path != current_local_path:
            _restore_local_path(new_local_path, current_local_path)
        raise

    document.local_path = new_local_path
    return {"local_moved": new_local_path != current_local_path, "drive_updated": drive_updated}
