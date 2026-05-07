from __future__ import annotations

import re
from pathlib import Path

from app.config import settings
from app.services.document_classifier import document_type_folder


def documents_root() -> Path:
    root = Path(settings.documents_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def temp_pdfs_root() -> Path:
    root = Path(settings.temp_pdfs_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_root() -> Path:
    root = Path(settings.data_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_folder_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", value or "").strip()
    return cleaned or "Other"


def sanitize_file_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value or "").strip(" .")
    return cleaned or "document.pdf"


def save_temp_pdf(message_id: str, attachment_name: str, pdf_bytes: bytes) -> Path:
    temp_name = sanitize_file_name(f"{message_id}_{attachment_name}")
    temp_path = temp_pdfs_root() / temp_name
    temp_path.write_bytes(pdf_bytes)
    return temp_path


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _same_file_content(first: Path, second: Path) -> bool:
    try:
        return first.read_bytes() == second.read_bytes()
    except FileNotFoundError:
        return False


def move_to_final_storage(
    *,
    temp_path: Path,
    supplier: str,
    document_type: str,
    final_name: str,
    needs_review: bool = False,
) -> Path:
    destination_root = documents_root()
    if needs_review:
        destination_root = destination_root / "Needs Review"

    destination_dir = (
        destination_root
        / sanitize_folder_name(supplier)
        / document_type_folder(document_type)
    )
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = destination_dir / sanitize_file_name(final_name)
    if destination.exists() and _same_file_content(temp_path, destination):
        temp_path.unlink(missing_ok=True)
        return destination

    destination = _dedupe_path(destination)
    temp_path.replace(destination)
    return destination
