from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.services.document_extraction_rules import extract_currency
from app.services.document_metadata import TABLE_HEADER_TOKENS, extract_document_date, extract_reference
from app.services.document_serialization import parse_document_date

MULTI_INVOICE_PATTERN = re.compile(r"\bINVOICE\s+\d{4,}\b", flags=re.IGNORECASE)
AMOUNT_CAPTURE_PATTERN = re.compile(r"[€$£]?\s*(\d[\d,]*\.\d{2})")
TOTAL_LABEL_GROUPS = (
    (r"grand total",),
    (r"invoice total",),
    (r"total due", r"amount due"),
    (r"order total",),
    (r"^total$",),
)
VAT_LABEL_GROUPS = (
    (r"total vat amount",),
    (r"vat total",),
    (r"^vat$",),
)
AMOUNT_MATCH_EPSILON = Decimal("0.05")


def _normalize_amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _collect_amounts(lines: list[str], start: int, end: int) -> list[Decimal]:
    candidates: list[Decimal] = []
    for line in lines[start:end]:
        for raw in AMOUNT_CAPTURE_PATTERN.findall(line):
            value = _normalize_amount(raw)
            if value is not None:
                candidates.append(value)
    return candidates


def _looks_like_table_header(lines: list[str], index: int) -> bool:
    context = " ".join(lines[max(0, index - 3) : index + 4]).lower()
    return sum(token in context for token in TABLE_HEADER_TOKENS) >= 3


def _find_summary_total_index(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip().lower() != "total":
            continue
        if _looks_like_table_header(lines, index):
            continue
        return index
    return None


def _find_total_triplet(candidates: list[Decimal]) -> tuple[Decimal, Decimal, Decimal] | None:
    limited = candidates[:5]
    for first_index, first in enumerate(limited[:-2]):
        for second_index in range(first_index + 1, len(limited) - 1):
            second = limited[second_index]
            combined = first + second
            for third in limited[second_index + 1 :]:
                if abs(combined - third) <= AMOUNT_MATCH_EPSILON:
                    return first, second, third
    return None


def _is_plausible_vat(candidate: Decimal, total_amount: Decimal | None) -> bool:
    if candidate <= 0:
        return False
    if total_amount is None:
        return True
    if candidate >= total_amount:
        return False
    ratio = candidate / total_amount
    return Decimal("0.01") <= ratio <= Decimal("0.35")


def _extract_candidate_total(lines: list[str]) -> Decimal | None:
    total_index = _find_summary_total_index(lines)
    if total_index is not None:
        summary_candidates = _collect_amounts(lines, total_index, min(len(lines), total_index + 12))
        triplet = _find_total_triplet(summary_candidates)
        if triplet is not None:
            return triplet[2]
        if summary_candidates:
            return summary_candidates[0]

    for label_group in TOTAL_LABEL_GROUPS:
        for index, line in enumerate(lines):
            if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in label_group):
                continue
            if line.strip().lower() == "total" and _looks_like_table_header(lines, index):
                continue
            candidates = _collect_amounts(lines, index, min(len(lines), index + 12))
            if candidates:
                return candidates[0]

    all_candidates = _collect_amounts(lines, 0, len(lines))
    if all_candidates:
        return max(all_candidates)
    return None


def _extract_candidate_vat(lines: list[str], total_amount: Decimal | None) -> Decimal | None:
    total_index = _find_summary_total_index(lines)
    if total_index is not None:
        summary_candidates = _collect_amounts(lines, total_index, min(len(lines), total_index + 12))
        triplet = _find_total_triplet(summary_candidates)
        if triplet is not None:
            return min(triplet[0], triplet[1])

        for index in range(total_index - 1, max(-1, total_index - 8), -1):
            if lines[index].strip().lower() != "vat":
                continue
            if _looks_like_table_header(lines, index):
                continue
            candidates = _collect_amounts(lines, index, min(total_index + 1, index + 4))
            for candidate in candidates:
                if _is_plausible_vat(candidate, total_amount):
                    return candidate

    for label_group in VAT_LABEL_GROUPS:
        for index, line in enumerate(lines):
            if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in label_group):
                continue
            if line.strip().lower() == "vat" and _looks_like_table_header(lines, index):
                continue
            candidates = _collect_amounts(lines, index, min(len(lines), index + 12))
            for candidate in candidates:
                if _is_plausible_vat(candidate, total_amount):
                    return candidate
            if candidates and total_amount is None:
                return candidates[0]
    return None


def split_multi_invoice_sections(text: str) -> list[str]:
    matches = list(MULTI_INVOICE_PATTERN.finditer(text or ""))
    if len(matches) < 2:
        return []

    boundaries = [match.start() for match in matches]
    boundaries.append(len(text or ""))
    sections: list[str] = []
    for index, start in enumerate(boundaries[:-1]):
        section = (text or "")[start : boundaries[index + 1]].strip()
        if section:
            sections.append(section)
    return sections


def extract_multi_invoice_candidates(
    *,
    text: str,
    document_type: str,
    subject: str = "",
) -> list[dict]:
    if document_type not in {"invoice", "credit_note"}:
        return []

    sections = split_multi_invoice_sections(text)
    if not sections:
        return []

    candidates: list[dict] = []
    for section in sections:
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        extracted_date = extract_document_date(section, subject)
        if extracted_date is None:
            match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", section)
            if match:
                extracted_date = datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()
        document_date = parse_document_date(extracted_date)
        reference = extract_reference(section, subject, "")
        amount = _extract_candidate_total(lines)
        vat_amount = _extract_candidate_vat(lines, amount)
        currency = extract_currency(section)

        if reference is None and amount is None and vat_amount is None and document_date is None:
            continue

        candidates.append(
            {
                "candidate_index": len(candidates) + 1,
                "reference": reference,
                "document_date": document_date,
                "amount": amount,
                "vat_amount": vat_amount,
                "currency": currency,
                "section_text": section,
            }
        )

    return candidates
