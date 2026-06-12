from __future__ import annotations

import base64
import json
from datetime import datetime, date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import settings
from app.models import Document
from app.services.statement_arithmetic import (
    ArithmeticRow,
    classify_statement_row_kind,
    is_non_settlement_statement_kind,
    verify_statement_arithmetic,
)
from app.services.supplier_profiles import (
    PARSER_FAMILY_DIAGEO_ERP,
    PARSER_FAMILY_GENERIC_STATEMENT,
    PARSER_FAMILY_STATEMENT_OF_ACCOUNT,
    PARSER_FAMILY_TRADE_STATEMENT,
    canonicalize_supplier_name,
    detect_statement_parser_family,
    is_operator_entity,
)


AI_EXTRACTION_PROVIDER = "openai"
# Bump when prompt wording changes so cached eval results are invalidated.
AI_EXTRACTION_PROMPT_VERSION = "v4"


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
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    note: str | None = None
    entries: list[AIDocumentStatementEntry] = Field(default_factory=list)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value):
        return normalize_currency_code(value)


CURRENCY_NAME_CODES = {
    "euro": "EUR",
    "euros": "EUR",
    "€": "EUR",
    "pound": "GBP",
    "pounds": "GBP",
    "sterling": "GBP",
    "£": "GBP",
    "dollar": "USD",
    "dollars": "USD",
    "$": "USD",
}


def normalize_currency_code(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in CURRENCY_NAME_CODES:
        return CURRENCY_NAME_CODES[lowered]
    if len(cleaned) == 3 and cleaned.isalpha():
        return cleaned.upper()
    return None


def statement_arithmetic_for_ai_result(ai_result: AIDocumentExtractionResult):
    return verify_statement_arithmetic(
        rows=[
            ArithmeticRow(
                kind=classify_statement_row_kind(entry.transaction_type, reference=entry.reference),
                amount=entry.amount,
                event_date=entry.event_date,
            )
            for entry in ai_result.entries
        ],
        opening_balance=ai_result.opening_balance,
        closing_balance=ai_result.closing_balance,
        total_due=ai_result.total_due,
        settlement_discount_total=ai_result.settlement_discount_total,
        statement_kind=ai_result.statement_kind or "statement",
        period_start=ai_result.period_start,
    )


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
    page_images: list[bytes] | None = None,
    repair_context: str | None = None,
) -> AIDocumentExtractionResult | None:
    if not ai_extraction_available():
        return None
    if not extracted_text.strip() and not page_images:
        return None

    raw_response = await _run_ai_extraction_request(
        model=settings.ai_document_extraction_model,
        messages=_build_ai_extraction_messages(
            document=document,
            extracted_text=extracted_text,
            page_images=page_images,
            repair_context=repair_context,
        ),
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
    prefer_ai_amount: bool = False,
) -> dict:
    merged = dict(extraction_fields)

    if ai_result.document_type and document.document_type == "unknown":
        document.document_type = ai_result.document_type

    ai_supplier = ai_result.supplier if not is_operator_entity(ai_result.supplier) else None
    if ai_supplier and (document.supplier == "Other" or is_operator_entity(document.supplier)):
        document.supplier = canonicalize_supplier_name(ai_supplier) or ai_supplier

    if ai_result.document_date and merged.get("document_date") is None:
        merged["document_date"] = ai_result.document_date

    if ai_result.reference and _weak_reference(merged.get("reference"), document.document_type):
        merged["reference"] = ai_result.reference

    # With page images the model reads the document's true layout; allow it to
    # correct a rules-extracted amount (e.g. a discounted total grabbed instead
    # of the gross), but only when it is confident and clearly read the same
    # document (matching reference).
    ai_amount_override = (
        prefer_ai_amount
        and ai_result.amount is not None
        and (ai_result.confidence_score or 0.0) >= settings.ai_document_extraction_min_confidence
        and _same_reference(ai_result.reference, merged.get("reference"))
    )
    if ai_result.amount is not None and (_weak_amount(merged.get("amount")) or ai_amount_override):
        merged["amount"] = ai_result.amount

    if ai_result.vat_amount is not None and (merged.get("vat_amount") is None or ai_amount_override):
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
    if document.document_type == "statement":
        merged = _apply_statement_quality(document=document, merged=merged, ai_result=ai_result)
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


def _same_reference(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    normalize = lambda value: "".join(ch for ch in value.lower() if ch.isalnum()).lstrip("0")  # noqa: E731
    return normalize(left) == normalize(right)


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


def _build_ai_extraction_messages(
    *,
    document: Document,
    extracted_text: str,
    page_images: list[bytes] | None = None,
    repair_context: str | None = None,
) -> list[dict]:
    statement_family = None
    statement_family_instructions = ""
    statement_entry_contract = ""
    if document.document_type == "statement":
        statement_family = detect_statement_parser_family(
            supplier=document.supplier,
            text=extracted_text,
        )
        statement_family_instructions = _statement_family_instructions(statement_family)
        statement_entry_contract = (
            "For statements, keep one JSON entry per financial row in the same order it appears in the document. "
            "Do not merge multiple rows into one entry and do not reuse statement totals as row amounts. "
            "Use `reference` for the row's main invoice/payment/credit reference. "
            "Use `clearing_reference` only for a second linked document number or clearing document if it is distinct. "
            "Use `transaction_type` values that preserve the source wording when possible, such as `INVOIC`, `PAYMNT`, `CRNOTE`, `Invoice`, `Receipt`, or `Cr.Note`. "
            "If a row amount is not visible for a specific row, leave `amount` null instead of guessing. "
            "Recover `opening_balance`, `closing_balance`, `total_due`, and `settlement_discount_total` whenever the statement states them; report them exactly as printed and never compute them yourself. "
            "Do not emit opening-balance, closing-balance, balance-forward (B/FWD), or other running-balance lines as entries; report those figures only in the balance fields. "
            "Set `raw_text` to a short row-level excerpt, not the whole page."
        )

    system_message = {
        "role": "system",
        "content": (
            "You extract structured bookkeeping data from supplier PDFs. "
            "Return one strict JSON object only. Prefer gross totals for amount. "
            "For statements, recover account details, period, totals, and row entries. "
            "When the document is a statement, prioritize row-level recovery over generic summarization. "
            "Do not invent values. Leave unknown fields null."
        ),
    }

    supplier_hint = document.supplier
    if supplier_hint == "Other" or is_operator_entity(supplier_hint):
        supplier_hint = "unknown"

    user_text = (
        f"Document type hint: {document.document_type}\n"
        f"Supplier hint: {supplier_hint}\n"
        "The supplier is the business that issued the document, never the customer, "
        "recipient, or account holder named on it.\n"
        f"Attachment name: {document.attachment_name}\n"
        f"Email subject: {document.source_email_subject or ''}\n\n"
        + (
            f"Statement parser family hint: {statement_family or 'unknown'}\n"
            f"{statement_entry_contract}\n"
            f"{statement_family_instructions}\n\n"
            if document.document_type == "statement"
            else ""
        )
        + (
            "If the document is an operational statement that explicitly says it is not financial, "
            "set `is_financial` to false and return no financial entries.\n\n"
            if document.document_type == "statement"
            else ""
        )
        + (
            "The attached page images are the authoritative source for table layout: read rows, "
            "column alignment, and amounts from the images. Use the extracted text below to confirm "
            "exact reference numbers, dates, and digits.\n\n"
            if page_images
            else ""
        )
        + (f"REPAIR ATTEMPT: {repair_context}\n\n" if repair_context else "")
        +
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
        '"opening_balance": decimal|null, '
        '"closing_balance": decimal|null, '
        '"note": string|null, '
        '"entries": ['
        '{"event_date":"YYYY-MM-DD"|null,"reference":string|null,"transaction_type":string|null,'
        '"due_date":"YYYY-MM-DD"|null,"clearing_reference":string|null,"amount":decimal|null,"raw_text":string|null}'
        "]"
        "}\n\n"
        f"Document text:\n{extracted_text}"
    )

    if not page_images:
        return [system_message, {"role": "user", "content": user_text}]

    content: list[dict] = [{"type": "text", "text": user_text}]
    for image_bytes in page_images:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
    return [system_message, {"role": "user", "content": content}]


def _unique_reasons(reasons: list[str]) -> list[str]:
    unique: list[str] = []
    for reason in reasons:
        if reason and reason not in unique:
            unique.append(reason)
    return unique


def _looks_like_financial_statement_row(entry: AIDocumentStatementEntry) -> bool:
    return bool(entry.reference or entry.clearing_reference or entry.transaction_type or entry.amount is not None)


def _is_invoice_or_credit_row(entry: AIDocumentStatementEntry) -> bool:
    transaction_type = (entry.transaction_type or "").strip().lower()
    return any(token in transaction_type for token in ("invoic", "invoice", "crnote", "cr.note", "credit"))


def _is_payment_row(entry: AIDocumentStatementEntry) -> bool:
    transaction_type = (entry.transaction_type or "").strip().lower()
    return any(token in transaction_type for token in ("paymnt", "payment", "receipt", "dd-"))


def _apply_statement_quality(
    *,
    document: Document,
    merged: dict,
    ai_result: AIDocumentExtractionResult,
) -> dict:
    statement_kind = ai_result.statement_kind or "statement"
    is_financial = ai_result.is_financial if ai_result.is_financial is not None else True
    existing_reasons = [
        reason
        for reason in merged.get("review_reasons", [])
        if reason
        not in {
            "low_confidence_extraction",
            "statement_rows_missing_amounts",
            "statement_no_financial_rows",
            "statement_unbalanced",
        }
    ]
    financial_rows = [entry for entry in ai_result.entries if _looks_like_financial_statement_row(entry)]
    rows_missing_amounts = [
        entry
        for entry in financial_rows
        if entry.amount is None and (_is_invoice_or_credit_row(entry) or _is_payment_row(entry))
    ]
    has_period = bool(ai_result.period_start or ai_result.period_end)
    has_totals = any(
        value is not None
        for value in (
            ai_result.total_due,
            ai_result.closing_balance,
            ai_result.settlement_discount_total,
            ai_result.amount,
        )
    )
    invoice_rows = [entry for entry in financial_rows if _is_invoice_or_credit_row(entry)]
    payment_rows = [entry for entry in financial_rows if _is_payment_row(entry)]

    score = float(merged.get("confidence_score") or ai_result.confidence_score or 0.0)
    score = max(score, 0.45 if is_financial else 0.7)
    if ai_result.account_number or ai_result.account_name:
        score += 0.08
    if has_period:
        score += 0.12
    if has_totals:
        score += 0.08
    if financial_rows:
        score += min(0.22, len(financial_rows) * 0.03)
    if invoice_rows:
        score += 0.08
    if payment_rows:
        score += 0.08
    if rows_missing_amounts:
        score -= min(0.4, len(rows_missing_amounts) * 0.12)
        row_count = max(len(invoice_rows) + len(payment_rows), 1)
        if len(rows_missing_amounts) / row_count >= 0.5:
            score = min(score, 0.64)

    review_reasons = list(existing_reasons)
    if is_financial and not is_non_settlement_statement_kind(statement_kind) and not financial_rows and not has_totals:
        review_reasons.append("statement_no_financial_rows")
        score -= 0.22
    if rows_missing_amounts:
        review_reasons.append("statement_rows_missing_amounts")
    if not has_period and not is_non_settlement_statement_kind(statement_kind):
        score -= 0.08

    arithmetic = statement_arithmetic_for_ai_result(ai_result)
    if arithmetic.is_balanced:
        score = max(score, 0.9)
    elif arithmetic.is_unbalanced:
        review_reasons.append("statement_unbalanced")
        score = min(score, 0.55)

    score = round(max(0.0, min(score, 0.99)), 2)
    review_reasons = _unique_reasons(review_reasons)
    if score < 0.7:
        review_reasons = _unique_reasons([*review_reasons, "low_confidence_extraction"])

    merged["confidence_score"] = score
    merged["review_reasons"] = review_reasons
    merged["needs_review"] = bool(review_reasons)
    if review_reasons:
        merged["extraction_status"] = "review"
    else:
        merged["extraction_status"] = "extracted"
    return merged


def _statement_family_instructions(statement_family: str | None) -> str:
    if statement_family == PARSER_FAMILY_DIAGEO_ERP:
        return (
            "This is an ERP-style supplier statement. Flattened OCR may list columns in separate blocks. "
            "Reconstruct rows by aligning document references, transaction types, event dates, due dates, clearing docs, and row amounts in order. "
            "Prefer row-level invoice/payment amounts over closing balance or settlement discount totals. "
            "Use the Billing Doc column as each row's `reference` (a 10-digit number such as 9263290802 for invoices or 2503701436 for payments) "
            "and the Clearing Doc column as `clearing_reference`; the Customer Reference values starting with 'D' belong in `raw_text` only. "
            "The Total Due figure is the closing balance of these statements. "
            "If the document is a SUB ACCOUNT STATEMENT tracking accumulated discounts, set `statement_kind` to `sub_account_statement`, "
            "report the opening and closing balances, and return no entries."
        )
    if statement_family == PARSER_FAMILY_STATEMENT_OF_ACCOUNT:
        return (
            "This is a statement of account. Each financial row usually has a reference/document number, a document type, a document date, a due date, and an original or adjusted amount. "
            "Capture invoice, payment, and credit rows separately. If both a reference number and a document number appear, use the main row identifier as `reference` and the other as `clearing_reference` when it is meaningfully distinct. "
            "If the layout shows an Amount Paid column per item, also emit one `PAYMNT` entry per non-zero paid amount, using the same document number as its `reference` and the paid amount's absolute value (or its sign if negative)."
        )
    if statement_family == PARSER_FAMILY_TRADE_STATEMENT:
        return (
            "This is a trade account statement. Preserve invoice, receipt, and credit-note rows separately, including direct-debit receipt references like `DD-29-04`. "
            "Use the per-row charge or receipt amount, not the running balance, as the row `amount`."
        )
    if statement_family == PARSER_FAMILY_GENERIC_STATEMENT:
        return (
            "This is a generic supplier statement. Recover statement period, balances, and any row-level invoice/payment/credit references that can be tied to amounts and dates."
        )
    return (
        "Treat this as a supplier statement if it contains account-period activity, balances, or invoice/payment rows."
    )


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
