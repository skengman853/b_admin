from __future__ import annotations

import re
from pathlib import Path


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value or "").strip("_").lower()
    return cleaned or "unknown"


def build_document_filename(
    *,
    supplier: str,
    document_type: str,
    original_filename: str,
    document_date: str | None = None,
    reference: str | None = None,
    amount: str | None = None,
) -> str:
    date_part = document_date or "unknown_date"
    reference_part = slugify(reference or Path(original_filename).stem or "unknown_ref")
    supplier_part = slugify(supplier)
    type_part = slugify(document_type)
    amount_part = slugify((amount or "unknown_amount").replace(".", "_"))
    return f"{date_part}_{supplier_part}_{type_part}_{reference_part}_{amount_part}.pdf"
