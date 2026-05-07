from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_document_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_document_amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def normalize_source_received_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_document_record(
    *,
    gmail_message_id: str,
    attachment_index: int,
    source_email_sender: str,
    source_email_subject: str,
    source_received_at: datetime | None,
    stored_file: dict[str, Any],
) -> dict[str, Any]:
    return {
        "gmail_message_id": gmail_message_id,
        "attachment_index": attachment_index,
        "attachment_name": stored_file["attachment_name"],
        "supplier": stored_file["supplier"],
        "document_type": stored_file["document_type"],
        "document_date": parse_document_date(stored_file.get("document_date")),
        "reference": stored_file.get("reference"),
        "amount": parse_document_amount(stored_file.get("amount")),
        "local_path": stored_file["saved_path"],
        "needs_review": bool(stored_file.get("needs_review")),
        "review_reasons": list(stored_file.get("review_reasons") or []),
        "source_email_sender": source_email_sender,
        "source_email_subject": source_email_subject,
        "source_received_at": normalize_source_received_at(source_received_at),
    }
