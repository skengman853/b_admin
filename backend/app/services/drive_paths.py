from __future__ import annotations

from pathlib import Path

from app.config import settings


def drive_path_parts_for_local_path(local_path: str) -> list[str]:
    path = Path(local_path)
    parts = list(path.parts[:-1])
    if parts and parts[0] == settings.documents_root:
        return [settings.drive_documents_root, *parts[1:]]
    return [settings.drive_documents_root, *parts]
