from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.document_classifier import classify_document_type
from app.services.document_extraction import extract_documents
from app.services.document_metadata import extract_document_date, extract_reference
from app.services.document_registry import upsert_document_record
from app.services.local_storage import copy_to_final_storage
from app.services.supplier_rules import canonicalize_supplier_name, detect_supplier
from app.services.vatbook_import import backend_root


PUB_HINTS = {
    "careys": "Careys Bar",
    "careys bar": "Careys Bar",
    "canal": "Canal Turn",
    "canal turn": "Canal Turn",
    "corr cross": "Corr Cross",
}
KNOWN_DOCUMENT_SUFFIXES = {".pdf"}
KNOWN_DOCUMENT_TYPES = {"invoice", "statement", "credit_note", "receipt", "unknown"}
DATE_TOKEN_PATTERNS = (
    re.compile(r"(\d{2})[./-](\d{2})[./-](\d{4})"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
)
REFERENCE_PATTERNS = (
    re.compile(r"\b(?:invoice\s+number|invoice\s+no|inv\s+no|invoice|statement|receipt|credit\s+note)\s*[-#:]*\s*([A-Z0-9-]{2,})\b", re.IGNORECASE),
    re.compile(r"\b(TCT\d{3,})\b", re.IGNORECASE),
)


@dataclass(slots=True)
class LocalDocumentImportItem:
    relative_path: str
    supplier: str | None
    document_type: str | None
    pub_hint: str | None
    status: str
    reason: str | None
    saved_path: str | None
    document_id: str | None


@dataclass(slots=True)
class LocalDocumentImportResult:
    source_path: str
    scanned_files: int
    eligible_files: int
    imported_documents: int
    extracted_documents: int
    skipped_files: int
    results: list[LocalDocumentImportItem]


def resolve_local_archive_path(source_path: str) -> Path:
    root = backend_root().resolve()
    candidate = Path(source_path)
    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0] == "backend":
            candidate = Path(*candidate.parts[1:])
        candidate = root / candidate

    resolved = candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("source_path must point to a file or directory inside the backend directory")
    if not resolved.exists():
        raise FileNotFoundError(f"Local archive path was not found: {resolved}")
    return resolved


async def import_documents_from_local_archive(
    *,
    user: User,
    db: AsyncSession,
    source_path: str,
    limit: int,
    supplier_filters: list[str] | None = None,
    document_types: list[str] | None = None,
    pub_filters: list[str] | None = None,
    month: str | None = None,
    include_archives: bool = False,
    recurse: bool = True,
    extract_after_import: bool = True,
) -> LocalDocumentImportResult:
    resolved_path = resolve_local_archive_path(source_path)
    normalized_supplier_filters = [value.strip().lower() for value in (supplier_filters or []) if value.strip()]
    normalized_pub_filters = [value.strip().lower() for value in (pub_filters or []) if value.strip()]
    normalized_document_types = {
        value.strip().lower()
        for value in (document_types or [])
        if value.strip()
    }
    if normalized_document_types and not normalized_document_types.issubset(KNOWN_DOCUMENT_TYPES):
        unsupported = ", ".join(sorted(normalized_document_types - KNOWN_DOCUMENT_TYPES))
        raise ValueError(f"Unsupported document types: {unsupported}")

    target_month = _parse_month(month) if month else None
    files = _collect_candidate_files(resolved_path, recurse=recurse)

    results: list[LocalDocumentImportItem] = []
    imported_document_ids: list = []
    imported_document_id_set: set = set()
    scanned_files = 0
    eligible_files = 0
    skipped_files = 0

    for file_path in files:
        scanned_files += 1
        relative_path = file_path.relative_to(resolved_path) if resolved_path.is_dir() else Path(file_path.name)
        path_parts = relative_path.parts[:-1]
        relative_path_text = relative_path.as_posix()

        if not include_archives and any(part.lower() == "archive" for part in path_parts):
            skipped_files += 1
            results.append(
                LocalDocumentImportItem(
                    relative_path=relative_path_text,
                    supplier=None,
                    document_type=None,
                    pub_hint=None,
                    status="skipped",
                    reason="archive_directory",
                    saved_path=None,
                    document_id=None,
                )
            )
            continue

        supplier = _infer_supplier(relative_path)
        document_type = _infer_document_type(relative_path)
        pub_hint = _infer_pub_hint(relative_path)
        date_hint = _infer_date_hint(relative_path)

        if normalized_document_types and document_type not in normalized_document_types:
            skipped_files += 1
            results.append(
                LocalDocumentImportItem(
                    relative_path=relative_path_text,
                    supplier=supplier,
                    document_type=document_type,
                    pub_hint=pub_hint,
                    status="skipped",
                    reason="document_type_filtered",
                    saved_path=None,
                    document_id=None,
                )
            )
            continue

        if document_type == "unknown" and "unknown" not in normalized_document_types:
            skipped_files += 1
            results.append(
                LocalDocumentImportItem(
                    relative_path=relative_path_text,
                    supplier=supplier,
                    document_type=document_type,
                    pub_hint=pub_hint,
                    status="skipped",
                    reason="unknown_document_type",
                    saved_path=None,
                    document_id=None,
                )
            )
            continue

        if normalized_supplier_filters and not _matches_filters(
            normalized_supplier_filters,
            supplier,
            relative_path_text,
        ):
            skipped_files += 1
            results.append(
                LocalDocumentImportItem(
                    relative_path=relative_path_text,
                    supplier=supplier,
                    document_type=document_type,
                    pub_hint=pub_hint,
                    status="skipped",
                    reason="supplier_filtered",
                    saved_path=None,
                    document_id=None,
                )
            )
            continue

        if normalized_pub_filters and not _matches_filters(
            normalized_pub_filters,
            pub_hint,
            relative_path_text,
        ):
            skipped_files += 1
            results.append(
                LocalDocumentImportItem(
                    relative_path=relative_path_text,
                    supplier=supplier,
                    document_type=document_type,
                    pub_hint=pub_hint,
                    status="skipped",
                    reason="pub_filtered",
                    saved_path=None,
                    document_id=None,
                )
            )
            continue

        if target_month and (date_hint is None or not date_hint.startswith(target_month)):
            skipped_files += 1
            results.append(
                LocalDocumentImportItem(
                    relative_path=relative_path_text,
                    supplier=supplier,
                    document_type=document_type,
                    pub_hint=pub_hint,
                    status="skipped",
                    reason="month_filtered",
                    saved_path=None,
                    document_id=None,
                )
            )
            continue

        eligible_files += 1
        if len(imported_document_ids) >= limit:
            skipped_files += 1
            results.append(
                LocalDocumentImportItem(
                    relative_path=relative_path_text,
                    supplier=supplier,
                    document_type=document_type,
                    pub_hint=pub_hint,
                    status="skipped",
                    reason="limit_reached",
                    saved_path=None,
                    document_id=None,
                )
            )
            continue

        review_reasons = _review_reasons(supplier=supplier, document_type=document_type)
        stored_path = copy_to_final_storage(
            source_path=file_path,
            supplier=supplier,
            document_type=document_type,
            final_name=_build_import_filename(file_path=file_path, pub_hint=pub_hint),
            needs_review=bool(review_reasons),
        )
        stored_file = {
            "attachment_name": file_path.name,
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
            gmail_message_id=_build_local_message_id(file_path),
            attachment_index=0,
            source_email_sender="local-archive",
            source_email_subject=relative_path_text,
            source_received_at=datetime.fromtimestamp(file_path.stat().st_mtime),
            stored_file=stored_file,
        )
        is_duplicate_import = document.id in imported_document_id_set
        if not is_duplicate_import:
            imported_document_ids.append(document.id)
            imported_document_id_set.add(document.id)
        results.append(
            LocalDocumentImportItem(
                relative_path=relative_path_text,
                supplier=supplier,
                document_type=document_type,
                pub_hint=pub_hint,
                status="deduped" if is_duplicate_import else "imported",
                reason="existing_imported_document" if is_duplicate_import else None,
                saved_path=str(stored_path),
                document_id=str(document.id),
            )
        )

    extracted_documents = 0
    if imported_document_ids and extract_after_import:
        extraction_summary = await extract_documents(
            user=user,
            db=db,
            limit=len(imported_document_ids),
            document_ids=imported_document_ids,
            force=True,
        )
        extracted_documents = extraction_summary["extracted"]
    else:
        await db.commit()

    return LocalDocumentImportResult(
        source_path=str(resolved_path.relative_to(backend_root())),
        scanned_files=scanned_files,
        eligible_files=eligible_files,
        imported_documents=len(imported_document_ids),
        extracted_documents=extracted_documents,
        skipped_files=skipped_files,
        results=results,
    )


def _collect_candidate_files(source_path: Path, *, recurse: bool) -> list[Path]:
    if source_path.is_file():
        return [source_path] if source_path.suffix.lower() in KNOWN_DOCUMENT_SUFFIXES else []
    iterator = source_path.rglob("*") if recurse else source_path.glob("*")
    return sorted(
        path
        for path in iterator
        if path.is_file() and path.suffix.lower() in KNOWN_DOCUMENT_SUFFIXES and not path.name.startswith(".")
    )


def _infer_supplier(relative_path: Path) -> str:
    first_segment = relative_path.parts[0] if relative_path.parts else "Other"
    detected = detect_supplier(
        sender="",
        subject=first_segment,
        attachment_name=relative_path.name,
        email_text=relative_path.as_posix(),
    )
    if detected != "Other":
        return detected
    canonical = canonicalize_supplier_name(first_segment)
    return canonical or "Other"


def _infer_document_type(relative_path: Path) -> str:
    path_text = " ".join(relative_path.parts[:-1]).lower()
    if "credit note" in path_text or "credit notes" in path_text:
        return "credit_note"
    if "statement" in path_text or "statements" in path_text:
        return "statement"
    if "receipt" in path_text or "receipts" in path_text:
        return "receipt"
    if "invoice" in path_text or "invoices" in path_text or "bills" in path_text:
        return "invoice"
    return classify_document_type(relative_path.name, relative_path.name, relative_path.as_posix())


def _infer_pub_hint(relative_path: Path) -> str | None:
    for part in relative_path.parts[:-1]:
        lowered = part.strip().lower()
        if lowered in PUB_HINTS:
            return PUB_HINTS[lowered]
    return None


def _infer_date_hint(relative_path: Path) -> str | None:
    source_text = relative_path.as_posix()
    filename_hint = extract_document_date(relative_path.name, relative_path.name)
    if filename_hint:
        return filename_hint

    for pattern in DATE_TOKEN_PATTERNS:
        for match in pattern.finditer(source_text):
            parsed = _normalize_date_match(match.groups())
            if parsed:
                return parsed
    return None


def _infer_reference_hint(relative_path: Path) -> str | None:
    filename = relative_path.name
    inferred = extract_reference("", attachment_name=filename)
    if inferred:
        return inferred
    for pattern in REFERENCE_PATTERNS:
        match = pattern.search(filename)
        if match:
            return match.group(1).strip()
    return None


def _build_import_filename(*, file_path: Path, pub_hint: str | None) -> str:
    file_name = re.sub(r"\s+-\s+Linked(?=\.[A-Za-z0-9]+$)", "", file_path.name, flags=re.IGNORECASE)
    if pub_hint and pub_hint.lower() not in file_name.lower():
        return f"{pub_hint} - {file_name}"
    return file_name


def _build_local_message_id(file_path: Path) -> str:
    digest = hashlib.sha1(str(file_path.resolve()).encode("utf-8")).hexdigest()  # noqa: S324
    return f"local-archive-{digest}"


def _review_reasons(*, supplier: str, document_type: str) -> list[str]:
    reasons: list[str] = []
    if supplier == "Other":
        reasons.append("unknown_supplier")
    if document_type == "unknown":
        reasons.append("unknown_document_type")
    return reasons


def _parse_month(month: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("month must use YYYY-MM format")
    return month


def _matches_filters(filters: list[str], *values: str | None) -> bool:
    haystacks = [value.lower() for value in values if value]
    return any(filter_value in haystack for filter_value in filters for haystack in haystacks)


def _normalize_date_match(groups: tuple[str, ...]) -> str | None:
    parts = tuple(group for group in groups if group)
    try:
        if len(parts[0]) == 4:
            parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            parsed = date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (TypeError, ValueError):
        return None
    return parsed.isoformat()
