from __future__ import annotations

import re
from datetime import datetime


DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%B %d, %Y",
    "%d %B %Y",
)

AMOUNT_PATTERN = re.compile(r"[€$£]?\s*(\d[\d,]*\.\d{2})")
REFERENCE_TOKEN = r"([A-Z0-9-]*\d[A-Z0-9-]*)"
TABLE_HEADER_TOKENS = ("description", "quantity", "qty", "unit", "price", "discount", "rate", "amount")


def _normalize_date(raw: str, *, preferred_numeric_order: str | None = None) -> str | None:
    cleaned = " ".join((raw or "").strip().split())
    numeric_formats = {
        "dmy": ("%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y"),
        "mdy": ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"),
    }

    format_order: list[str] = []
    if preferred_numeric_order in numeric_formats:
        format_order.extend(numeric_formats[preferred_numeric_order])
        other_order = "mdy" if preferred_numeric_order == "dmy" else "dmy"
        format_order.extend(numeric_formats[other_order])
    else:
        format_order.extend(numeric_formats["dmy"])
        format_order.extend(numeric_formats["mdy"])
    format_order.extend(("%B %d, %Y", "%d %B %Y"))

    for fmt in format_order:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extract_document_date(text: str, subject: str = "") -> str | None:
    if all(token in (text or "") for token in ("Bill To:", "Balance Due", "Due Date:", "Invoice No:")):
        mdy_patterns = (
            r"Date[:\s]+(\d{2}/\d{2}/\d{4})",
            r"Due Date[:\s]+(\d{2}/\d{2}/\d{4})",
        )
        for pattern in mdy_patterns:
            match = re.search(pattern, text or "", flags=re.IGNORECASE)
            if match:
                normalized = _normalize_date(match.group(1), preferred_numeric_order="mdy")
                if normalized:
                    return normalized

    patterns = (
        r"Invoice Date[:\s]+(\d{2}[/-]\d{2}[/-]\d{2,4})",
        r"Date paid[:\s]+([A-Za-z]+ \d{1,2}, \d{4})",
        r"Service date[:\s]+(\d{2}[/-]\d{2}[/-]\d{2,4})",
        r"Statement\s+\((?:\d{2}\s+[A-Za-z]+\s+\d{4})\s*-\s*(\d{2}\s+[A-Za-z]+\s+\d{4})\)",
    )
    haystacks = [text or "", subject or ""]
    for haystack in haystacks:
        for pattern in patterns:
            match = re.search(pattern, haystack, flags=re.IGNORECASE)
            if match:
                normalized = _normalize_date(match.group(1))
                if normalized:
                    return normalized

    generic_patterns = (
        r"(\d{2}[/-]\d{2}[/-]\d{2,4})",
        r"([A-Za-z]+ \d{1,2}, \d{4})",
        r"(\d{2}\s+[A-Za-z]+\s+\d{4})",
    )
    for haystack in haystacks:
        for pattern in generic_patterns:
            matches = re.findall(pattern, haystack, flags=re.IGNORECASE)
            for raw in matches:
                normalized = _normalize_date(raw)
                if normalized:
                    return normalized
    return None


def extract_reference(text: str, subject: str = "", attachment_name: str = "") -> str | None:
    reference_groups = (
        (
            "receipt",
            (
                rf"Receipt number[: \t]+{REFERENCE_TOKEN}",
                rf"(?:^|[\\/])Receipt-{REFERENCE_TOKEN}(?:\.[A-Za-z0-9]+)?$",
                rf"#({REFERENCE_TOKEN[1:-1]})",
            ),
        ),
        (
            "invoice",
            (
                rf"Invoice No\.?[: \t]+{REFERENCE_TOKEN}",
                rf"Invoice number[: \t]+{REFERENCE_TOKEN}",
                r"\bINVOICE\s+(\d{4,})\b",
                rf"(?:^|[\\/])Invoice[-_\s]+{REFERENCE_TOKEN}(?:\.[A-Za-z0-9]+)?$",
            ),
        ),
        (
            "generic",
            (
                r"\b(PFINV-\d+)\b",
                r"\b(OUT-\d+)\b",
                r"Statement\s+\d+\(([A-Z0-9]+)\)",
                r"order\s+(\d{4,})",
            ),
        ),
    )

    text_haystack = text or ""
    subject_haystack = subject or ""
    attachment_haystack = attachment_name or ""
    haystacks = [text_haystack, subject_haystack, attachment_haystack]
    primary_context = " ".join([text_haystack, attachment_haystack]).lower()
    fallback_context = " ".join(haystacks).lower()
    preferred_types: list[str] = []
    if "receipt" in primary_context:
        preferred_types.append("receipt")
    if "invoice" in primary_context:
        preferred_types.append("invoice")
    if not preferred_types:
        if "receipt" in fallback_context:
            preferred_types.append("receipt")
        if "invoice" in fallback_context:
            preferred_types.append("invoice")
    preferred_types.append("generic")
    preferred_types.extend(kind for kind, _ in reference_groups if kind not in preferred_types)

    for preferred_type in preferred_types:
        patterns = next(patterns for kind, patterns in reference_groups if kind == preferred_type)
        if preferred_type in {"receipt", "invoice"}:
            ordered_haystacks = [attachment_haystack, text_haystack, subject_haystack]
        else:
            ordered_haystacks = [text_haystack, subject_haystack, attachment_haystack]
        for haystack in ordered_haystacks:
            for pattern in patterns:
                match = re.search(pattern, haystack, flags=re.IGNORECASE)
                if match:
                    return match.group(1).strip()
    return None


def _normalize_amount(raw: str) -> str | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "").strip()
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
        whole, _, fraction = cleaned.partition(".")
        if not fraction:
            fraction = "00"
        if len(fraction) == 1:
            fraction += "0"
        return f"{whole}.{fraction}"
    return None


def _find_amounts_in_lines(
    lines: list[str],
    label_patterns: tuple[str, ...],
    *,
    window_size: int = 10,
    strategy: str = "last",
) -> str | None:
    for idx, line in enumerate(lines):
        if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in label_patterns):
            continue

        window = lines[idx : idx + window_size]
        candidates: list[str] = []
        for candidate_line in window:
            for raw in AMOUNT_PATTERN.findall(candidate_line):
                normalized = _normalize_amount(raw)
                if normalized:
                    candidates.append(normalized)
        if candidates:
            if strategy == "first":
                return candidates[0]
            return candidates[-1]
    return None


def _find_total_like_amount(
    lines: list[str],
    label_patterns: tuple[str, ...],
    *,
    immediate_window_size: int = 3,
    fallback_window_size: int = 10,
) -> str | None:
    for idx, line in enumerate(lines):
        if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in label_patterns):
            continue
        if line.strip().lower() == "total":
            context = " ".join(lines[max(0, idx - 3) : idx + 4]).lower()
            if sum(token in context for token in TABLE_HEADER_TOKENS) >= 3:
                continue

        immediate_window = lines[idx : idx + immediate_window_size]
        immediate_candidates: list[float] = []
        for candidate_line in immediate_window:
            for raw in AMOUNT_PATTERN.findall(candidate_line):
                normalized = _normalize_amount(raw)
                if normalized:
                    immediate_candidates.append(float(normalized))
        if immediate_candidates:
            return f"{max(immediate_candidates):.2f}"

        fallback_window = lines[idx : idx + fallback_window_size]
        fallback_candidates: list[float] = []
        for candidate_line in fallback_window:
            for raw in AMOUNT_PATTERN.findall(candidate_line):
                normalized = _normalize_amount(raw)
                if normalized:
                    fallback_candidates.append(float(normalized))
        if fallback_candidates:
            return f"{max(fallback_candidates):.2f}"

    return None


def extract_amount(text: str, document_type: str = "unknown") -> str | None:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]

    if document_type == "statement":
        amount = _find_amounts_in_lines(
            lines,
            (r"outstanding balance", r"total due"),
            window_size=6,
            strategy="first",
        )
        if amount:
            return amount

        amount = _find_amounts_in_lines(lines, (r"total balance",), window_size=6, strategy="first")
        if amount:
            return amount

    if document_type == "receipt":
        receipt_label_groups = (
            (r"amount paid",),
            (r"^total$",),
            (r"subtotal",),
        )
        for label_group in receipt_label_groups:
            amount = _find_total_like_amount(lines, label_group, fallback_window_size=8)
            if amount:
                return amount

    invoice_label_groups = (
        (r"grand total",),
        (r"invoice total",),
        (r"total due", r"amount due"),
        (r"order total",),
        (r"^total$",),
        (r"balance due",),
    )
    for label_group in invoice_label_groups:
        amount = _find_total_like_amount(lines, label_group, fallback_window_size=10)
        if amount:
            return amount

    all_amounts: list[float] = []
    for line in lines:
        for raw in AMOUNT_PATTERN.findall(line):
            normalized = _normalize_amount(raw)
            if normalized:
                all_amounts.append(float(normalized))
    if all_amounts:
        return f"{max(all_amounts):.2f}"

    return None
