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
    # Capture stage (doc 29): if the email has a PDF attachment, capture it.
    # The old behaviour required an 'invoice/statement' keyword (or known
    # sender) and silently dropped real invoices from new suppliers with vague
    # subjects. Capture is now dumb on purpose — every PDF is kept and sorting
    # happens later. INCLUDE/EXCLUDE patterns are retained only for reference.
    if not attachment_names:
        return False, "no_pdf_attachments"
    return True, "has_pdf_attachment"
