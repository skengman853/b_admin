from __future__ import annotations

from datetime import datetime, MAXYEAR
from typing import Any, Sequence


def _canonical_sort_key(item: Any) -> tuple[int, int, datetime, str]:
    has_drive_file = 0 if getattr(item, "drive_file_id", None) else 1
    has_synced_at = 0 if getattr(item, "synced_at", None) else 1
    created_at = getattr(item, "created_at", None) or datetime(MAXYEAR, 1, 1)
    identifier = str(getattr(item, "id", ""))
    return (has_drive_file, has_synced_at, created_at, identifier)


def pick_canonical_document(documents: Sequence[Any]) -> tuple[Any, list[Any]]:
    ordered = sorted(documents, key=_canonical_sort_key)
    return ordered[0], list(ordered[1:])
