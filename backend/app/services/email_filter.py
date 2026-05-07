from __future__ import annotations

import re

INCLUDE_PATTERNS = (
    r"\binvoice\b",
    r"\binvoices\b",
    r"\bstatement\b",
    r"\binv\b",
    r"\bcredit\b",
    r"\bcredits\b",
    r"\bcredit note\b",
    r"\bcredit memo\b",
)

EXCLUDE_PATTERNS = (
    r"\btransactions?\b",
    r"\bmarketing\b",
    r"\bnewsletter\b",
    r"\bpromotion\b",
    r"\bpromo\b",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def should_process_email(
    *,
    subject: str,
    snippet: str,
    attachment_names: list[str],
    known_supplier: bool = False,
) -> tuple[bool, str]:
    if not attachment_names:
        return False, "no_pdf_attachments"

    combined = " ".join(
        part for part in [subject, snippet, " ".join(attachment_names)] if part
    )

    if _matches_any(combined, EXCLUDE_PATTERNS):
        return False, "matched_exclude_rule"

    if known_supplier:
        return True, "known_supplier"

    if _matches_any(combined, INCLUDE_PATTERNS):
        return True, "matched_include_rule"

    return False, "no_include_rule_match"
