from __future__ import annotations


def classify_document_type(subject: str, filename: str, pdf_text: str = "") -> str:
    primary_haystack = " ".join([filename or "", pdf_text or ""]).lower()
    fallback_haystack = " ".join([subject or "", filename or "", pdf_text or ""]).lower()

    if "credit note" in primary_haystack or "credit memo" in primary_haystack:
        return "credit_note"
    if "statement" in primary_haystack or "account statement" in primary_haystack:
        return "statement"
    if "receipt" in primary_haystack or "amount paid" in primary_haystack or "date paid" in primary_haystack:
        return "receipt"
    if any(term in primary_haystack for term in ("invoice", "vat invoice", "tax invoice", "invoice no", "invoice number")):
        return "invoice"

    haystack = fallback_haystack
    if "credit note" in haystack or "credit memo" in haystack:
        return "credit_note"
    if "statement" in haystack or "account statement" in haystack:
        return "statement"
    if "receipt" in haystack or "amount paid" in haystack or "date paid" in haystack:
        return "receipt"
    if any(term in haystack for term in ("invoice", "vat invoice", "tax invoice", "invoice no", "invoice number")):
        return "invoice"
    return "unknown"


def document_type_folder(document_type: str) -> str:
    return {
        "invoice": "Invoices",
        "statement": "Statements",
        "credit_note": "Credit Notes",
        "receipt": "Receipts",
    }.get(document_type, "Other")
