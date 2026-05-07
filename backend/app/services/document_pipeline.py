from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GmailConnection, User
from app.services.document_classifier import classify_document_type
from app.services.document_metadata import extract_amount, extract_document_date, extract_reference
from app.services.email_filter import should_process_email
from app.services.file_namer import build_document_filename
from app.services.gmail_client import fetch_message_with_pdfs, get_gmail_service, list_recent_message_ids
from app.services.local_storage import move_to_final_storage, save_temp_pdf
from app.services.pdf_text import extract_pdf_text
from app.services.supplier_rules import detect_supplier, is_known_supplier
from app.services.tracking import has_processed_message, record_processed_message, tracking_file_path


def _review_reasons(*, supplier: str, document_type: str) -> list[str]:
    reasons: list[str] = []
    if supplier == "Other":
        reasons.append("unknown_supplier")
    if document_type == "unknown":
        reasons.append("unknown_document_type")
    return reasons


async def scan_recent_documents(
    *,
    user: User,
    connection: GmailConnection,
    db: AsyncSession,
    days: int,
    max_messages: int,
    force: bool = False,
) -> dict:
    service = await get_gmail_service(connection, db)
    message_ids = list_recent_message_ids(service, days=days, max_results=max_messages)

    results: list[dict] = []
    processed_messages = 0
    skipped_messages = 0
    saved_files = 0
    needs_review_messages = 0
    needs_review_files = 0
    files_by_supplier: Counter[str] = Counter()
    files_by_type: Counter[str] = Counter()

    for message_id in message_ids:
        if not force and has_processed_message(str(user.id), message_id):
            skipped_messages += 1
            results.append(
                {
                    "message_id": message_id,
                    "sender": "",
                    "subject": "",
                    "status": "skipped",
                    "reason": "already_processed",
                    "files": [],
                }
            )
            continue

        message = fetch_message_with_pdfs(service, message_id)
        attachment_names = [attachment.filename for attachment in message.pdf_attachments]
        known_supplier = is_known_supplier(message.sender, message.subject)
        should_process, reason = should_process_email(
            subject=message.subject,
            snippet=message.snippet,
            attachment_names=attachment_names,
            known_supplier=known_supplier,
        )

        if not should_process:
            skipped_messages += 1
            record_processed_message(
                str(user.id),
                message.message_id,
                {
                    "status": "skipped",
                    "reason": reason,
                    "sender": message.sender,
                    "subject": message.subject,
                    "attachments_saved": 0,
                },
            )
            results.append(
                {
                    "message_id": message.message_id,
                    "sender": message.sender,
                    "subject": message.subject,
                    "status": "skipped",
                    "reason": reason,
                    "files": [],
                }
            )
            continue

        stored_files: list[dict] = []
        message_needs_review = False
        for attachment in message.pdf_attachments:
            temp_path = save_temp_pdf(message.message_id, attachment.filename, attachment.data)
            pdf_text = extract_pdf_text(attachment.data)
            supplier = detect_supplier(
                message.sender,
                message.subject,
                pdf_text,
                attachment.filename,
                message.body_text or message.snippet,
            )
            document_type = classify_document_type(message.subject, attachment.filename, pdf_text)
            document_date = extract_document_date(pdf_text, message.subject)
            reference = extract_reference(pdf_text, message.subject, attachment.filename)
            amount = extract_amount(pdf_text, document_type)
            review_reasons = _review_reasons(supplier=supplier, document_type=document_type)
            needs_review = bool(review_reasons)
            final_name = build_document_filename(
                supplier=supplier,
                document_type=document_type,
                original_filename=attachment.filename,
                document_date=document_date,
                reference=reference,
                amount=amount,
            )
            final_path = move_to_final_storage(
                temp_path=temp_path,
                supplier=supplier,
                document_type=document_type,
                final_name=final_name,
                needs_review=needs_review,
            )

            files_by_supplier[supplier] += 1
            files_by_type[document_type] += 1
            if needs_review:
                message_needs_review = True
                needs_review_files += 1

            stored_files.append(
                {
                    "attachment_name": attachment.filename,
                    "supplier": supplier,
                    "document_type": document_type,
                    "document_date": document_date,
                    "reference": reference,
                    "amount": amount,
                    "needs_review": needs_review,
                    "review_reasons": review_reasons,
                    "saved_path": str(final_path),
                }
            )

        processed_messages += 1
        saved_files += len(stored_files)
        if message_needs_review:
            needs_review_messages += 1
        record_processed_message(
            str(user.id),
            message.message_id,
                {
                    "status": "processed",
                    "reason": reason,
                    "sender": message.sender,
                    "subject": message.subject,
                    "snippet": message.snippet,
                    "attachments_saved": len(stored_files),
                    "files": stored_files,
                    "received_at": message.received_at.isoformat() if message.received_at else None,
                },
        )
        results.append(
            {
                "message_id": message.message_id,
                "sender": message.sender,
                "subject": message.subject,
                "status": "processed",
                "reason": reason,
                "files": stored_files,
            }
        )

    connection.last_synced_at = datetime.utcnow()
    await db.commit()

    return {
        "scanned_messages": len(message_ids),
        "processed_messages": processed_messages,
        "skipped_messages": skipped_messages,
        "saved_files": saved_files,
        "needs_review_messages": needs_review_messages,
        "needs_review_files": needs_review_files,
        "files_by_supplier": dict(files_by_supplier),
        "files_by_type": dict(files_by_type),
        "tracking_file": str(tracking_file_path()),
        "results": results,
    }
