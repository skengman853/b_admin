from __future__ import annotations

import re
from email.utils import parseaddr

from app.services.supplier_profiles import (
    canonicalize_supplier_name as canonicalize_known_supplier_name,
    match_known_supplier_in_text,
)

FREE_MAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "outlook.com",
    "yahoo.com",
}

LOW_CONFIDENCE_SENDER_NAMES = {
    "no-reply",
    "noreply",
    "do not reply",
}


def extract_sender_email(sender: str) -> str:
    _, address = parseaddr(sender or "")
    return address.lower()


def extract_sender_display_name(sender: str) -> str:
    name, _ = parseaddr(sender or "")
    return name.strip()


def _clean_subject(subject: str) -> str:
    cleaned = subject or ""
    while True:
        updated = re.sub(r"^\s*(fwd?|fw|re):\s*", "", cleaned, flags=re.IGNORECASE)
        if updated == cleaned:
            return cleaned.strip()
        cleaned = updated


def _clean_candidate(candidate: str) -> str:
    cleaned = re.sub(r"\s+", " ", candidate or "").strip(" -,:;")
    cleaned = re.sub(r"\s+\([^)]*\)$", "", cleaned).strip()
    cleaned = re.sub(r"\s+#?[A-Z0-9]+-\d+$", "", cleaned).strip()
    return cleaned


def _match_known_supplier(haystack: str) -> str | None:
    return match_known_supplier_in_text(haystack)


def canonicalize_supplier_name(candidate: str) -> str | None:
    cleaned = _clean_candidate(candidate)
    if not cleaned:
        return None
    return canonicalize_known_supplier_name(cleaned) or cleaned


def _extract_supplier_from_subject(subject: str) -> str | None:
    cleaned_subject = _clean_subject(subject)

    trading_as = re.search(r"\bt\/a\s+(.+)$", cleaned_subject, flags=re.IGNORECASE)
    if trading_as:
        candidate = _clean_candidate(trading_as.group(1))
        if candidate:
            known = _match_known_supplier(candidate.lower())
            return known or candidate

    patterns = (
        r"\bfrom\s+(.+)$",
        r"\binvoice for\s+(.+)$",
        r"^(.+?)\s+statement\b",
        r"^(.+?)\s+credit note\b",
    )

    for pattern in patterns:
        match = re.search(pattern, cleaned_subject, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_candidate(match.group(1))
        if candidate:
            known = _match_known_supplier(candidate.lower())
            return known or candidate
    return None


def _extract_supplier_from_pdf_text(pdf_text: str) -> str | None:
    if not pdf_text:
        return None

    first_lines = [line.strip() for line in pdf_text.splitlines()[:25] if line.strip()]
    for line in first_lines:
        trading_as = re.search(r"\bt\/a\s+(.+)$", line, flags=re.IGNORECASE)
        if trading_as:
            candidate = _clean_candidate(trading_as.group(1))
            if candidate:
                known = _match_known_supplier(candidate.lower())
                return known or candidate

    combined = " ".join(first_lines).lower()
    known = _match_known_supplier(combined)
    if known:
        return known

    banned = {
        "invoice",
        "proforma invoice",
        "customer details",
        "service details",
        "statement",
        "order charges",
    }
    for line in first_lines:
        line_lower = line.lower()
        if line_lower in banned:
            continue
        if any(keyword in line_lower for keyword in ("limited", "ltd", "services", "corporation", "cash & carry", "skip hire", "amusements")):
            return _clean_candidate(line)
    return None


def _extract_supplier_from_email_text(email_text: str) -> str | None:
    if not email_text:
        return None

    lowered = email_text.lower()
    known = _match_known_supplier(lowered)
    if known:
        return known

    match = re.search(r"^from:\s*([^<\n]+)", email_text, flags=re.IGNORECASE | re.MULTILINE)
    if match:
        candidate = _clean_candidate(match.group(1))
        if candidate:
            known = _match_known_supplier(candidate.lower())
            return known or candidate

    return None


def detect_supplier(
    sender: str,
    subject: str,
    pdf_text: str = "",
    attachment_name: str = "",
    email_text: str = "",
) -> str:
    sender_email = extract_sender_email(sender)
    attachment_haystack = attachment_name.lower()
    haystack = " ".join(
        [sender_email, subject or "", pdf_text or "", attachment_name or "", email_text or ""]
    ).lower()

    subject_candidate = _extract_supplier_from_subject(subject)
    if subject_candidate:
        return subject_candidate

    known = _match_known_supplier(haystack)
    if known:
        return known

    if attachment_haystack:
        known = _match_known_supplier(attachment_haystack)
        if known:
            return known

    email_candidate = _extract_supplier_from_email_text(email_text)
    if email_candidate:
        return email_candidate

    pdf_candidate = _extract_supplier_from_pdf_text(pdf_text)
    if pdf_candidate:
        return pdf_candidate

    domain = sender_email.split("@", 1)[-1] if "@" in sender_email else ""
    local_part = sender_email.split("@", 1)[0] if "@" in sender_email else ""
    forwarded = bool(re.match(r"^\s*(fwd?|fw):", subject or "", flags=re.IGNORECASE))

    display_name = extract_sender_display_name(sender)
    if display_name and domain not in FREE_MAIL_DOMAINS and not forwarded:
        cleaned = re.sub(r"\s+", " ", display_name).strip()
        lowered_cleaned = cleaned.lower()
        if cleaned and "@" not in cleaned and not any(term in lowered_cleaned for term in LOW_CONFIDENCE_SENDER_NAMES):
            return cleaned

    if domain and domain not in FREE_MAIL_DOMAINS and not any(term in local_part for term in ("no-reply", "noreply")):
        stem = domain.split(".", 1)[0]
        if stem:
            return stem.replace("-", " ").replace("_", " ").title()

    return "Other"


def is_known_supplier(sender: str, subject: str) -> bool:
    sender_email = extract_sender_email(sender)
    haystack = " ".join([sender_email, subject or ""]).lower()
    return match_known_supplier_in_text(haystack) is not None
