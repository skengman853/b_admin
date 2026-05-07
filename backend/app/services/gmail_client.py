from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, UTC

from googleapiclient.discovery import build
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GmailConnection
from app.services.google_oauth import get_google_credentials


@dataclass
class GmailPdfAttachment:
    filename: str
    data: bytes


@dataclass
class GmailMessage:
    message_id: str
    subject: str
    sender: str
    snippet: str
    body_text: str
    received_at: datetime | None
    pdf_attachments: list[GmailPdfAttachment]


def _decode_base64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


async def get_gmail_service(connection: GmailConnection, db: AsyncSession):
    credentials = await get_google_credentials(connection, db)
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_recent_message_ids(service, *, days: int, max_results: int) -> list[str]:
    query = f"in:inbox -in:sent newer_than:{days}d has:attachment filename:pdf"
    response = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    return [item["id"] for item in response.get("messages", [])]


def _walk_parts(part: dict) -> list[dict]:
    parts = [part]
    for child in part.get("parts", []) or []:
        parts.extend(_walk_parts(child))
    return parts


def _extract_headers(payload: dict) -> dict[str, str]:
    return {header["name"]: header["value"] for header in payload.get("headers", [])}


def _extract_text_body(payload: dict) -> str:
    text_parts: list[str] = []
    for part in _walk_parts(payload):
        mime_type = part.get("mimeType") or ""
        if mime_type != "text/plain":
            continue
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        try:
            decoded = _decode_base64(data).decode("utf-8", errors="ignore").strip()
        except Exception:
            decoded = ""
        if decoded:
            text_parts.append(decoded)
    return "\n".join(text_parts).strip()


def _download_attachment(service, *, message_id: str, attachment_id: str) -> bytes:
    response = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )
    return _decode_base64(response["data"])


def fetch_message_with_pdfs(service, message_id: str) -> GmailMessage:
    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = message.get("payload", {})
    headers = _extract_headers(payload)
    pdf_attachments: list[GmailPdfAttachment] = []

    for part in _walk_parts(payload):
        filename = part.get("filename") or ""
        mime_type = part.get("mimeType") or ""
        if not filename and mime_type != "application/pdf":
            continue
        if filename and not filename.lower().endswith(".pdf") and mime_type != "application/pdf":
            continue

        body = part.get("body", {}) or {}
        data = body.get("data")
        attachment_id = body.get("attachmentId")

        if data:
            pdf_bytes = _decode_base64(data)
        elif attachment_id:
            pdf_bytes = _download_attachment(service, message_id=message_id, attachment_id=attachment_id)
        else:
            continue

        pdf_attachments.append(GmailPdfAttachment(filename=filename or "attachment.pdf", data=pdf_bytes))

    internal_date = message.get("internalDate")
    received_at = None
    if internal_date:
        received_at = datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)

    return GmailMessage(
        message_id=message_id,
        subject=headers.get("Subject", ""),
        sender=headers.get("From", ""),
        snippet=message.get("snippet", ""),
        body_text=_extract_text_body(payload),
        received_at=received_at,
        pdf_attachments=pdf_attachments,
    )
