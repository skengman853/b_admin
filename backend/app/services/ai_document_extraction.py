from __future__ import annotations

import json
from datetime import datetime, date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.models import Document


AI_EXTRACTION_PROVIDER = "openai"


class AIDocumentStatementEntry(BaseModel):
    event_date: date | None = None
    reference: str | None = None
    transaction_type: str | None = None
    due_date: date | None = None
    clearing_reference: str | None = None
    amount: Decimal | None = None
    raw_text: str | None = None


class AIDocumentExtractionResult(BaseModel):
    supplier: str | None = None
    document_type: str | None = None
    document_date: date | None = None
    reference: str | None = None
    amount: Decimal | None = None
    vat_amount: Decimal | None = None
    currency: str | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    is_financial: bool | None = None
    statement_kind: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    total_due: Decimal | None = None
    settlement_discount_total: Decimal | None = None
    closing_balance: Decimal | None = None
    note: str | None = None
    entries: list[AIDocumentStatementEntry] = Field(default_factory=list)


def ai_extraction_available() -> bool:
    return bool(settings.ai_document_extraction_enabled and _has_configured_openai_key(settings.openai_api_key))


def should_attempt_ai_extraction(
    *,
    document: Document,
    extraction_fields: dict,
) -> bool:
    if not ai_extraction_available():
        return False

    if document.document_type == "statement":
        return True

    if extraction_fields.get("extraction_status") == "review":
        return True

    confidence_score = extraction_fields.get("confidence_score")
    if confidence_score is not None and confidence_score < settings.ai_document_extraction_min_confidence:
        return True

    if document.document_type in {"invoice", "credit_note", "receipt"}:
        if (
            extraction_fields.get("document_date") is None
            or extraction_fields.get("reference") is None
            or extraction_fields.get("amount") is None
        ):
            return True

    return False


async def extract_document_with_ai(
    *,
    document: Document,
    extracted_text: str,
) -> AIDocumentExtractionResult | None:
    if not ai_extraction_available():
        return None
    if not extracted_text.strip():
        return None

    raw_response = await _run_ai_extraction_request(
        model=settings.ai_document_extraction_model,
        messages=_build_ai_extraction_messages(document=document, extracted_text=extracted_text),
    )
    if not raw_response:
        return None

    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError:
        return None

    try:
        return AIDocumentExtractionResult.model_validate(payload)
    except ValidationError:
        return None


def merge_ai_extraction(
    *,
    document: Document,
    extraction_fields: dict,
    ai_result: AIDocumentExtractionResult,
) -> dict:
    merged = dict(extraction_fields)

    if ai_result.document_type and document.document_type == "unknown":
        document.document_type = ai_result.document_type

    if ai_result.supplier and document.supplier == "Other":
        document.supplier = ai_result.supplier

    if ai_result.document_date and merged.get("document_date") is None:
        merged["document_date"] = ai_result.document_date

    if ai_result.reference and _weak_reference(merged.get("reference"), document.document_type):
        merged["reference"] = ai_result.reference

    if ai_result.amount is not None and _weak_amount(merged.get("amount")):
        merged["amount"] = ai_result.amount

    if ai_result.vat_amount is not None and merged.get("vat_amount") is None:
        merged["vat_amount"] = ai_result.vat_amount

    if ai_result.currency and not merged.get("currency"):
        merged["currency"] = ai_result.currency

    confidence_score = merged.get("confidence_score") or 0.0
    if ai_result.confidence_score is not None:
        merged["confidence_score"] = round(max(float(confidence_score), ai_result.confidence_score), 2)

    if document.document_type == "statement" and (
        ai_result.entries
        or ai_result.statement_kind
        or ai_result.total_due is not None
        or ai_result.closing_balance is not None
    ):
        merged["extraction_status"] = "extracted"
        review_reasons = [
            reason
            for reason in merged.get("review_reasons", [])
            if reason not in {"missing_document_date", "low_confidence_extraction"}
        ]
        merged["review_reasons"] = review_reasons
        merged["needs_review"] = bool(review_reasons)
    elif (
        document.document_type in {"invoice", "credit_note", "receipt"}
        and merged.get("document_date") is not None
        and merged.get("reference") is not None
        and merged.get("amount") is not None
        and (ai_result.confidence_score or 0.0) >= settings.ai_document_extraction_min_confidence
    ):
        merged["extraction_status"] = "extracted"
        review_reasons = [
            reason
            for reason in merged.get("review_reasons", [])
            if reason not in {"missing_document_date", "missing_amount", "low_confidence_extraction"}
        ]
        merged["review_reasons"] = review_reasons
        merged["needs_review"] = bool(review_reasons)

    document.ai_extraction_status = "completed"
    document.ai_extraction_provider = AI_EXTRACTION_PROVIDER
    document.ai_extraction_model = settings.ai_document_extraction_model
    document.ai_extraction_payload = ai_result.model_dump(mode="json")
    document.ai_extracted_at = datetime.utcnow()
    return merged


def _weak_reference(reference: str | None, document_type: str) -> bool:
    if not reference:
        return True
    normalized = reference.strip().lower()
    if normalized in {"date", "statement", "invoice"}:
        return True
    if document_type == "statement" and normalized.startswith("date"):
        return True
    return False


def _weak_amount(amount: Decimal | None) -> bool:
    return amount is None or amount <= Decimal("0.00")


def _has_configured_openai_key(api_key: str | None) -> bool:
    value = (api_key or "").strip()
    if not value:
        return False
    lowered = value.lower()
    placeholder_markers = (
        "your-openai",
        "your_openai",
        "change-me",
        "example",
    )
    return not any(marker in lowered for marker in placeholder_markers)


def _build_ai_extraction_messages(*, document: Document, extracted_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You extract structured bookkeeping data from supplier PDFs. "
                "Return one strict JSON object only. Prefer gross totals for amount. "
                "For statements, recover account details, period, totals, and row entries. "
                "Do not invent values. Leave unknown fields null."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Document type hint: {document.document_type}\n"
                f"Supplier hint: {document.supplier}\n"
                f"Attachment name: {document.attachment_name}\n"
                f"Email subject: {document.source_email_subject or ''}\n\n"
                "Return JSON with keys:\n"
                "{"
                '"supplier": string|null, '
                '"document_type": string|null, '
                '"document_date": "YYYY-MM-DD"|null, '
                '"reference": string|null, '
                '"amount": decimal|null, '
                '"vat_amount": decimal|null, '
                '"currency": string|null, '
                '"confidence_score": number|null, '
                '"is_financial": boolean|null, '
                '"statement_kind": string|null, '
                '"account_number": string|null, '
                '"account_name": string|null, '
                '"period_start": "YYYY-MM-DD"|null, '
                '"period_end": "YYYY-MM-DD"|null, '
                '"total_due": decimal|null, '
                '"settlement_discount_total": decimal|null, '
                '"closing_balance": decimal|null, '
                '"note": string|null, '
                '"entries": ['
                '{"event_date":"YYYY-MM-DD"|null,"reference":string|null,"transaction_type":string|null,'
                '"due_date":"YYYY-MM-DD"|null,"clearing_reference":string|null,"amount":decimal|null,"raw_text":string|null}'
                "]"
                "}\n\n"
                f"Document text:\n{extracted_text}"
            ),
        },
    ]


async def _run_ai_extraction_request(*, model: str, messages: list[dict[str, str]]) -> str | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=messages,
    )
    choice = response.choices[0] if response.choices else None
    if choice is None or choice.message is None:
        return None
    return choice.message.content or None
