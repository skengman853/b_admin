from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.services.document_metadata import extract_amount, extract_document_date, extract_reference

AMOUNT_CAPTURE_PATTERN = re.compile(r"[€$£]?\s*(\d[\d,]*\.\d{2})")
TABLE_HEADER_TOKENS = ("description", "quantity", "qty", "unit", "price", "discount", "rate", "amount")
MULTI_INVOICE_PATTERN = re.compile(r"\bINVOICE\s+\d{4,}\b", flags=re.IGNORECASE)


def _normalize_amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def extract_currency(text: str) -> str | None:
    haystack = (text or "").upper()
    if "EUR" in haystack or "€" in (text or ""):
        return "EUR"
    if "GBP" in haystack or "£" in (text or ""):
        return "GBP"
    if "USD" in haystack or "$" in (text or ""):
        return "USD"
    return None


def extract_vat_amount(text: str, document_type: str = "unknown") -> Decimal | None:
    if document_type in {"statement", "receipt", "unknown"}:
        return None

    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    explicit_patterns = (
        r"VAT\s+\d+(?:\.\d+)?%\s*\([^)]+\)\s*(?:\r?\n|\s)+[€$£]?\s*(\d[\d,]*\.\d{2})",
        r"Total VAT Amount(?:\s*[:\-]?\s*|\r?\n+)[€$£]?\s*(\d[\d,]*\.\d{2})",
        r"VAT Total(?:\s*[:\-]?\s*|\r?\n+)[€$£]?\s*(\d[\d,]*\.\d{2})",
    )
    for pattern in explicit_patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return _normalize_amount(match.group(1))

    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if "tax amount" in line_lower:
            window = lines[idx : idx + 5]
            candidates: list[Decimal] = []
            for candidate_line in window:
                for raw in AMOUNT_CAPTURE_PATTERN.findall(candidate_line):
                    value = _normalize_amount(raw)
                    if value is not None:
                        candidates.append(value)
            if candidates:
                return candidates[-1]

    for idx, line in enumerate(lines):
        if line.strip().lower() != "vat":
            continue
        context = " ".join(lines[max(0, idx - 3) : idx + 4]).lower()
        if sum(token in context for token in TABLE_HEADER_TOKENS) >= 3:
            continue
        window = lines[idx : idx + 4]
        for candidate_line in window:
            for raw in AMOUNT_CAPTURE_PATTERN.findall(candidate_line):
                value = _normalize_amount(raw)
                if value is not None:
                    return value
    return None


def has_multiple_invoice_records(text: str, document_type: str = "unknown") -> bool:
    if document_type not in {"invoice", "credit_note"}:
        return False
    return len(MULTI_INVOICE_PATTERN.findall(text or "")) > 1


def has_suspicious_amounts(
    *,
    amount: Decimal | None,
    vat_amount: Decimal | None,
    document_type: str,
) -> bool:
    if document_type not in {"invoice", "credit_note"}:
        return False
    if amount is None or amount <= 0:
        return True
    if vat_amount is None:
        return False
    if vat_amount <= 0 or vat_amount >= amount:
        return True
    ratio = vat_amount / amount
    return ratio > Decimal("0.35") or ratio < Decimal("0.01")


def _adjust_confidence_for_extraction_flags(
    confidence_score: float,
    *,
    multiple_invoice_records: bool,
    suspicious_amounts: bool,
) -> float:
    if multiple_invoice_records:
        confidence_score -= 0.35
    if suspicious_amounts:
        confidence_score -= 0.25
    return round(max(0.0, min(confidence_score, 0.99)), 2)


def _determine_extraction_status(
    *,
    extracted_text: str,
    multiple_invoice_records: bool,
    suspicious_amounts: bool,
) -> str:
    if not extracted_text.strip():
        return "failed"
    if multiple_invoice_records or suspicious_amounts:
        return "review"
    return "extracted"


def _build_extraction_review_reasons(
    *,
    existing_review_reasons: list[str] | None,
    document_type: str,
    document_date,
    amount: Decimal | None,
    confidence_score: float,
    multiple_invoice_records: bool,
    suspicious_amounts: bool,
) -> list[str]:
    reasons = list(existing_review_reasons or [])
    if multiple_invoice_records:
        reasons.append("multiple_invoice_records")
    if suspicious_amounts and not multiple_invoice_records:
        reasons.append("suspicious_amounts")
    if document_date is None:
        reasons.append("missing_document_date")
    if document_type in {"invoice", "credit_note", "receipt"} and amount is None:
        reasons.append("missing_amount")
    if confidence_score < 0.7:
        reasons.append("low_confidence_extraction")

    unique_reasons: list[str] = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)
    return unique_reasons


def calculate_confidence_score(
    *,
    supplier: str,
    document_type: str,
    document_date,
    reference: str | None,
    amount: Decimal | None,
    vat_amount: Decimal | None,
    extracted_text: str,
    needs_review: bool,
) -> float:
    score = 0.0
    if supplier and supplier != "Other":
        score += 0.2
    if document_type and document_type != "unknown":
        score += 0.15
    if document_date:
        score += 0.2
    if reference:
        score += 0.15
    if amount is not None:
        score += 0.2
    if vat_amount is not None:
        score += 0.1
    if extracted_text.strip():
        score += 0.1
    if needs_review:
        score -= 0.2
    return round(max(0.0, min(score, 0.99)), 2)


def build_extraction_fields(
    *,
    extracted_text: str,
    supplier: str,
    document_type: str,
    subject: str = "",
    attachment_name: str = "",
    existing_document_date=None,
    existing_reference: str | None = None,
    existing_amount: Decimal | None = None,
    existing_vat_amount: Decimal | None = None,
    existing_currency: str | None = None,
    existing_review_reasons: list[str] | None = None,
    needs_review: bool = False,
    prefer_existing_values: bool = False,
) -> dict:
    document_date = existing_document_date
    if document_date is None or not prefer_existing_values:
        extracted_date_raw = extract_document_date(extracted_text, subject)
        if extracted_date_raw:
            document_date = datetime.fromisoformat(extracted_date_raw).date()

    reference = existing_reference if prefer_existing_values else None
    if reference is None:
        reference = existing_reference or extract_reference(extracted_text, subject, attachment_name)

    amount = existing_amount if prefer_existing_values else _normalize_amount(extract_amount(extracted_text, document_type))
    if amount is None and not prefer_existing_values:
        amount = existing_amount
    elif amount is None:
        amount = existing_amount

    multiple_invoice_records = has_multiple_invoice_records(extracted_text, document_type)
    vat_amount = existing_vat_amount if prefer_existing_values else extract_vat_amount(extracted_text, document_type)
    if vat_amount is None and not prefer_existing_values:
        vat_amount = existing_vat_amount
    elif vat_amount is None:
        vat_amount = existing_vat_amount
    currency = existing_currency if prefer_existing_values else extract_currency(extracted_text)
    if currency is None and not prefer_existing_values:
        currency = existing_currency
    elif currency is None:
        currency = existing_currency

    if multiple_invoice_records:
        reference = None
        amount = None
        vat_amount = None

    suspicious_amounts = has_suspicious_amounts(
        amount=amount,
        vat_amount=vat_amount,
        document_type=document_type,
    )
    confidence_score = calculate_confidence_score(
        supplier=supplier,
        document_type=document_type,
        document_date=document_date,
        reference=reference,
        amount=amount,
        vat_amount=vat_amount,
        extracted_text=extracted_text,
        needs_review=needs_review,
    )
    confidence_score = _adjust_confidence_for_extraction_flags(
        confidence_score,
        multiple_invoice_records=multiple_invoice_records,
        suspicious_amounts=suspicious_amounts,
    )
    extraction_status = _determine_extraction_status(
        extracted_text=extracted_text,
        multiple_invoice_records=multiple_invoice_records,
        suspicious_amounts=suspicious_amounts,
    )
    review_reasons = _build_extraction_review_reasons(
        existing_review_reasons=existing_review_reasons,
        document_type=document_type,
        document_date=document_date,
        amount=amount,
        confidence_score=confidence_score,
        multiple_invoice_records=multiple_invoice_records,
        suspicious_amounts=suspicious_amounts,
    )

    return {
        "document_date": document_date,
        "reference": reference,
        "amount": amount,
        "vat_amount": vat_amount,
        "currency": currency,
        "confidence_score": confidence_score,
        "extracted_text": extracted_text,
        "extraction_status": extraction_status,
        "extracted_at": datetime.utcnow(),
        "needs_review": needs_review or extraction_status == "review" or bool(review_reasons),
        "review_reasons": review_reasons,
    }
