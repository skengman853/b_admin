from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, MAXYEAR
from pathlib import PurePath
from typing import Any, Sequence

from app.services.supplier_profiles import compact_profile_key


def _extraction_rank(item: Any) -> int:
    status = (getattr(item, "extraction_status", None) or "").lower()
    if status in {"reviewed", "extracted"}:
        return 0
    if status == "review":
        return 1
    if status == "failed":
        return 3
    return 2


def _confidence_rank(item: Any) -> float:
    value = getattr(item, "confidence_score", None)
    if value is None:
        return 1.0
    return -float(value)


def _canonical_sort_key(item: Any) -> tuple[int, int, int, int, int, int, float, datetime, str]:
    has_storage = 0 if getattr(item, "storage_key", None) else 1
    has_drive_file = 0 if getattr(item, "drive_file_id", None) else 1
    has_synced_at = 0 if getattr(item, "synced_at", None) else 1
    review_penalty = 0 if not getattr(item, "needs_review", False) else 1
    has_extracted_text = 0 if getattr(item, "extracted_text", None) else 1
    created_at = getattr(item, "created_at", None) or datetime(MAXYEAR, 1, 1)
    identifier = str(getattr(item, "id", ""))
    return (
        has_storage,
        has_drive_file,
        has_synced_at,
        _extraction_rank(item),
        review_penalty,
        has_extracted_text,
        _confidence_rank(item),
        created_at,
        identifier,
    )


def _normalized_reference(value: str | None) -> str:
    reference = (value or "").strip().upper()
    if not reference:
        return ""
    if reference.isdigit():
        return reference.lstrip("0") or "0"
    return reference


def _normalized_amount(value: Any) -> str:
    if value is None:
        return ""
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ""
    return f"{decimal_value.quantize(Decimal('0.01'))}"


def _document_name_token(item: Any) -> str:
    attachment_name = getattr(item, "attachment_name", None)
    if attachment_name:
        return compact_profile_key(PurePath(str(attachment_name)).name)
    local_path = getattr(item, "local_path", None)
    if local_path:
        return compact_profile_key(PurePath(str(local_path)).name)
    storage_key = getattr(item, "storage_key", None)
    if storage_key:
        return compact_profile_key(PurePath(str(storage_key)).name)
    return ""


def document_duplicate_fingerprint(item: Any) -> str | None:
    document_type = compact_profile_key(getattr(item, "document_type", None))
    supplier = compact_profile_key(getattr(item, "supplier", None))
    if not document_type or not supplier:
        return None
    date_value = getattr(item, "document_date", None)
    document_date = date_value.isoformat() if hasattr(date_value, "isoformat") and date_value else ""
    reference = _normalized_reference(getattr(item, "reference", None))
    amount = _normalized_amount(getattr(item, "amount", None))
    name_token = _document_name_token(item)
    if reference:
        return f"{document_type}|{supplier}|{document_date}|ref:{reference}|name:{name_token}"
    if name_token and document_date and amount:
        return f"{document_type}|{supplier}|{document_date}|amt:{amount}|name:{name_token}"
    return None


def build_duplicate_groups(documents: Sequence[Any]) -> list[list[Any]]:
    if not documents:
        return []

    parent = list(range(len(documents)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    seen_by_key: dict[str, int] = {}
    for index, document in enumerate(documents):
        keys: list[str] = []
        local_path = getattr(document, "local_path", None)
        if local_path:
            keys.append(f"path:{local_path}")
        storage_key = getattr(document, "storage_key", None)
        if storage_key:
            keys.append(f"storage:{storage_key}")
        fingerprint = document_duplicate_fingerprint(document)
        if fingerprint:
            keys.append(f"fingerprint:{fingerprint}")

        for key in keys:
            existing_index = seen_by_key.get(key)
            if existing_index is None:
                seen_by_key[key] = index
            else:
                union(existing_index, index)

    groups: dict[int, list[Any]] = {}
    for index, document in enumerate(documents):
        groups.setdefault(find(index), []).append(document)
    return list(groups.values())


def pick_canonical_document(documents: Sequence[Any]) -> tuple[Any, list[Any]]:
    ordered = sorted(documents, key=_canonical_sort_key)
    return ordered[0], list(ordered[1:])
