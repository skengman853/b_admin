from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import re

from app.models import Document
from app.services.ai_document_extraction import AIDocumentExtractionResult
from app.services.supplier_profiles import (
    PARSER_FAMILY_DIAGEO_ERP,
    PARSER_FAMILY_GENERIC_STATEMENT,
    PARSER_FAMILY_STATEMENT_OF_ACCOUNT,
    PARSER_FAMILY_TRADE_STATEMENT,
    compact_profile_key,
    detect_statement_parser_family,
)

DATE_PATTERN = re.compile(r"\b(\d{2}[./]\d{2}[./]\d{2,4})\b")
DECIMAL_PATTERN = re.compile(r"(-?\d[\d,]*\.\d{2}-?)")

DIAGEO_TXN_TYPES = {
    "INVOIC",
    "PAYMNT",
    "CRNOTE",
    "CREDIT",
    "DEBIT",
}
CONNACHT_TXN_TYPES = {
    "INVOICE",
    "RECEIPT",
    "CR.NOTE",
    "CRNOTE",
    "CREDIT NOTE",
}
ACCOUNT_STATEMENT_TXN_TYPES = {
    "invoice",
    "payment",
    "credit note",
    "creditnote",
    "receipt",
}


@dataclass(slots=True)
class ParsedSupplierStatementEntry:
    event_date: date | None = None
    reference: str | None = None
    transaction_type: str | None = None
    due_date: date | None = None
    clearing_reference: str | None = None
    amount: Decimal | None = None
    raw_text: str | None = None


@dataclass(slots=True)
class ParsedSupplierStatement:
    statement_kind: str
    is_financial: bool
    account_number: str | None = None
    account_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    total_due: Decimal | None = None
    settlement_discount_total: Decimal | None = None
    closing_balance: Decimal | None = None
    invoice_references: list[str] = field(default_factory=list)
    payment_references: list[str] = field(default_factory=list)
    note: str | None = None
    entries: list[ParsedSupplierStatementEntry] = field(default_factory=list)


def parse_supplier_statement(document: Document) -> ParsedSupplierStatement | None:
    if document.document_type != "statement":
        return None

    ai_parsed = _parse_ai_extracted_statement(document)
    if ai_parsed is not None:
        return ai_parsed

    text = (document.extracted_text or "").strip()
    if not text:
        return None

    parser_family = detect_statement_parser_family(supplier=document.supplier, text=text)
    if parser_family is None:
        return None

    handler = PARSER_FAMILY_HANDLERS.get(parser_family)
    if handler is None:
        return None

    parsed = handler(document, text)
    if parsed is not None:
        return parsed
    if parser_family != PARSER_FAMILY_GENERIC_STATEMENT:
        return _parse_generic_statement(document, text)
    return None


def _parse_ai_extracted_statement(document: Document) -> ParsedSupplierStatement | None:
    payload = document.ai_extraction_payload or {}
    if not payload:
        return None

    try:
        ai_result = AIDocumentExtractionResult.model_validate(payload)
    except Exception:
        return None

    if (
        not ai_result.entries
        and ai_result.statement_kind is None
        and ai_result.is_financial is None
        and ai_result.total_due is None
        and ai_result.closing_balance is None
    ):
        return None

    entries = []
    for entry in ai_result.entries:
        normalized_amount = entry.amount
        if normalized_amount is not None and _is_payment_statement_type(entry.transaction_type):
            normalized_amount = abs(normalized_amount)
        if normalized_amount is not None and _is_invoice_statement_type(entry.transaction_type):
            normalized_amount = abs(normalized_amount)

        entries.append(
            ParsedSupplierStatementEntry(
                event_date=entry.event_date,
                reference=entry.reference,
                transaction_type=entry.transaction_type,
                due_date=entry.due_date,
                clearing_reference=entry.clearing_reference,
                amount=normalized_amount,
                raw_text=entry.raw_text,
            )
        )
    invoice_references = [
        entry.reference
        for entry in entries
        if entry.reference and _is_invoice_statement_type(entry.transaction_type)
    ]
    payment_references = [
        entry.reference
        for entry in entries
        if entry.reference and _is_payment_statement_type(entry.transaction_type)
    ]
    note_parts = ["Structured AI extraction was used for this statement."]
    if ai_result.note:
        note_parts.append(ai_result.note)

    inferred_statement_kind = ai_result.statement_kind
    if inferred_statement_kind is None and entries:
        has_invoice_or_credit = any(_is_invoice_statement_type(entry.transaction_type) for entry in entries)
        has_payment = any(_is_payment_statement_type(entry.transaction_type) for entry in entries)
        if has_invoice_or_credit and has_payment:
            inferred_statement_kind = "supplier_statement"

    return ParsedSupplierStatement(
        statement_kind=inferred_statement_kind or "statement",
        is_financial=ai_result.is_financial if ai_result.is_financial is not None else True,
        account_number=ai_result.account_number,
        account_name=ai_result.account_name,
        period_start=ai_result.period_start,
        period_end=ai_result.period_end or document.document_date,
        total_due=ai_result.total_due,
        settlement_discount_total=ai_result.settlement_discount_total,
        closing_balance=ai_result.closing_balance or ai_result.amount,
        invoice_references=invoice_references,
        payment_references=payment_references,
        note=" ".join(note_parts),
        entries=entries,
    )


def _parse_diageo_statement(document: Document, text: str) -> ParsedSupplierStatement | None:
    if "this is not a financial document" in text.lower():
        return ParsedSupplierStatement(
            statement_kind="keg_flow_statement",
            is_financial=False,
            account_number=_extract_account_number(text),
            account_name=_extract_account_name(text),
            note="Operational keg-flow support only. This document should not be treated as a financial settlement.",
        )

    if "sub account statement" in text.lower():
        period_start, period_end = _extract_period_range(text)
        return ParsedSupplierStatement(
            statement_kind="sub_account_statement",
            is_financial=True,
            account_number=_extract_account_number(text),
            account_name=_extract_account_name(text),
            period_start=period_start,
            period_end=period_end,
            closing_balance=_extract_value_after_label(text, "Closing Balance EUR"),
            note="Tracks accumulated discount and sub-account balances rather than direct invoice charges.",
        )

    if "statement" not in text.lower():
        return None

    lines = _normalized_lines(text)
    opening_balance_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Opening Balance @ ")),
        None,
    )
    if opening_balance_index is None:
        return ParsedSupplierStatement(
            statement_kind="supplier_statement",
            is_financial=True,
            account_number=_extract_account_number(text),
            account_name=_extract_account_name(text),
            total_due=_extract_value_after_label(text, "Total Due"),
            settlement_discount_total=_extract_value_after_label(text, "Total Sett Disc"),
            note="Supplier statement metadata parsed, but no structured transaction lines were detected.",
        )

    contact_name_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Contact Name:")),
        None,
    )
    contact_no_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Contact No.:")),
        None,
    )
    if contact_name_index is None or contact_no_index is None or contact_no_index < contact_name_index:
        return ParsedSupplierStatement(
            statement_kind="supplier_statement",
            is_financial=True,
            account_number=_extract_account_number(text),
            account_name=_extract_account_name(text),
            total_due=_extract_value_after_label(text, "Total Due"),
            settlement_discount_total=_extract_value_after_label(text, "Total Sett Disc"),
            note="Supplier statement metadata parsed, but the transaction columns could not be aligned confidently.",
        )

    event_dates = [
        parsed_date
        for line in lines[opening_balance_index + 1 : contact_name_index]
        for parsed_date in [_parse_date(line)]
        if parsed_date is not None
    ]

    type_index = next(
        (
            index
            for index in range(contact_no_index + 1, len(lines))
            if lines[index] in DIAGEO_TXN_TYPES
        ),
        None,
    )
    if type_index is None:
        return ParsedSupplierStatement(
            statement_kind="supplier_statement",
            is_financial=True,
            account_number=_extract_account_number(text),
            account_name=_extract_account_name(text),
            total_due=_extract_value_after_label(text, "Total Due"),
            settlement_discount_total=_extract_value_after_label(text, "Total Sett Disc"),
            note="Supplier statement metadata parsed, but no recognised Diageo transaction types were found.",
        )

    references = [
        line
        for line in lines[contact_no_index + 1 : type_index]
        if _looks_like_statement_reference(line)
    ]

    transaction_types: list[str] = []
    due_date_index = None
    for index in range(type_index, len(lines)):
        line = lines[index]
        if line in DIAGEO_TXN_TYPES:
            transaction_types.append(line)
            continue
        if transaction_types and _parse_date(line) is not None:
            due_date_index = index
            break
        if transaction_types:
            continue
    if due_date_index is None:
        due_dates: list[date] = []
    else:
        due_dates = []
        for line in lines[due_date_index:]:
            parsed_date = _parse_date(line)
            if parsed_date is None:
                if due_dates:
                    break
                continue
            due_dates.append(parsed_date)

    entry_count = min(len(event_dates), len(references), len(transaction_types))
    entries = [
        ParsedSupplierStatementEntry(
            event_date=event_dates[index],
            reference=references[index],
            transaction_type=transaction_types[index],
            due_date=due_dates[index] if index < len(due_dates) else None,
            raw_text=" ".join(
                part
                for part in (
                    event_dates[index].isoformat() if index < len(event_dates) else None,
                    references[index] if index < len(references) else None,
                    transaction_types[index] if index < len(transaction_types) else None,
                    due_dates[index].isoformat() if index < len(due_dates) else None,
                )
                if part
            ),
        )
        for index in range(entry_count)
    ]

    invoice_references = [
        entry.reference
        for entry in entries
        if entry.reference and entry.transaction_type == "INVOIC"
    ]
    payment_references = [
        entry.reference
        for entry in entries
        if entry.reference and entry.transaction_type == "PAYMNT"
    ]

    opening_balance_line = lines[opening_balance_index]
    period_start = _parse_date(opening_balance_line.replace("Opening Balance @ ", "", 1))

    note_parts = []
    if entries:
        note_parts.append(
            f"Parsed {len(entries)} Diageo statement line(s) with invoice/payment references."
        )
    if not entries:
        note_parts.append("Parsed statement totals only.")
    note_parts.append("Per-line gross values were not recovered reliably from the OCR column layout.")

    return ParsedSupplierStatement(
        statement_kind="supplier_statement",
        is_financial=True,
        account_number=_extract_account_number(text),
        account_name=_extract_account_name(text),
        period_start=period_start,
        period_end=document.document_date,
        total_due=_extract_value_after_label(text, "Total Due"),
        settlement_discount_total=_extract_value_after_label(text, "Total Sett Disc"),
        invoice_references=invoice_references,
        payment_references=payment_references,
        note=" ".join(note_parts),
        entries=entries,
    )


def _parse_generic_statement(document: Document, text: str) -> ParsedSupplierStatement | None:
    if "statement" not in text.lower():
        return None

    period_start, period_end = _extract_period_range(text)
    is_financial = "not a financial document" not in text.lower()
    note = "Parsed generic supplier statement metadata."
    if not is_financial:
        note = "Marked as non-financial by the document text."

    return ParsedSupplierStatement(
        statement_kind="statement",
        is_financial=is_financial,
        account_number=_extract_account_number(text),
        account_name=_extract_account_name(text),
        period_start=period_start,
        period_end=period_end or document.document_date,
        total_due=_extract_value_after_label(text, "Total Due"),
        settlement_discount_total=_extract_value_after_label(text, "Total Sett Disc"),
        closing_balance=_extract_value_after_label(text, "Closing Balance"),
        note=note,
    )


def _parse_statement_of_account(document: Document, text: str) -> ParsedSupplierStatement | None:
    lines = _normalized_lines(text)
    if "STATEMENT OF ACCOUNT" not in lines and not _looks_like_columnar_statement_of_account(lines):
        return None

    opening_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Opening Balance as on ")),
        None,
    )
    closing_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Closing Balance as on ")),
        None,
    )
    detail_lines = (
        lines[opening_index + 1 : closing_index]
        if opening_index is not None and closing_index is not None and closing_index > opening_index
        else []
    )
    entries = _parse_statement_of_account_entries(detail_lines)
    if not entries:
        entries = _parse_statement_of_account_columnar_entries(lines)
    invoice_references = [
        entry.reference
        for entry in entries
        if entry.reference and entry.transaction_type == "Invoice"
    ]
    payment_references = [
        entry.reference
        for entry in entries
        if entry.reference and entry.transaction_type == "Payment"
    ]
    note_parts = []
    if entries:
        note_parts.append(
            f"Parsed {len(entries)} account statement line(s) with invoice/payment movements."
        )
    else:
        note_parts.append("Parsed account statement metadata, but no reliable line items were recovered.")
    settlement_discount = _extract_value_after_label(text, "Settlement Discount of EUR")
    if settlement_discount is not None:
        note_parts.append("Settlement discount text was detected on the statement.")

    opening_balance = _extract_opening_or_closing_balance(lines, prefix="Opening Balance as on ")
    closing_balance = _extract_opening_or_closing_balance(lines, prefix="Closing Balance as on ")
    period_start, period_end = _extract_statement_of_account_period(lines)
    statement_date = _extract_statement_date(lines)

    return ParsedSupplierStatement(
        statement_kind="supplier_statement",
        is_financial=True,
        account_number=_extract_statement_of_account_number(lines) or _extract_account_number(text),
        account_name=_extract_statement_of_account_name(lines),
        period_start=period_start,
        period_end=period_end or statement_date or document.document_date,
        total_due=closing_balance,
        settlement_discount_total=settlement_discount,
        closing_balance=closing_balance,
        invoice_references=invoice_references,
        payment_references=payment_references,
        note=" ".join(note_parts),
        entries=entries,
    )


def _parse_connacht_statement(document: Document, text: str) -> ParsedSupplierStatement | None:
    if "statement" not in text.lower():
        return None

    lines = _normalized_lines(text)
    detail_start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lower().rstrip(":") in {"account no.", "account no", "a/c no.", "a/c no"}
        ),
        None,
    )
    detail_lines = lines[detail_start + 1 :] if detail_start is not None else lines
    stop_index = next(
        (
            index
            for index, line in enumerate(detail_lines)
            if line.startswith("To Pay Directly into Bank Name:")
        ),
        len(detail_lines),
    )
    detail_lines = detail_lines[:stop_index]

    entries = _parse_connacht_statement_entries(detail_lines)
    invoice_references = [
        entry.reference
        for entry in entries
        if entry.reference and entry.transaction_type == "Invoice"
    ]
    payment_references = [
        entry.reference
        for entry in entries
        if entry.reference and entry.transaction_type == "Receipt"
    ]
    receipt_count = sum(1 for entry in entries if entry.transaction_type == "Receipt")
    invoice_count = sum(1 for entry in entries if entry.transaction_type == "Invoice")
    credit_count = sum(1 for entry in entries if entry.transaction_type == "Cr.Note")

    month_end = document.document_date
    month_start = (
        date(month_end.year, month_end.month, 1) if month_end is not None else None
    )
    note_parts = []
    if entries:
        note_parts.append(
            f"Parsed {len(entries)} Connacht statement line(s): {receipt_count} receipt(s), {invoice_count} invoice(s), {credit_count} credit note(s)."
        )
        if len(entries) < 6:
            note_parts.append("OCR flattening hid some earlier statement rows, so this is a partial line recovery.")
    else:
        note_parts.append("Parsed Connacht statement metadata, but the OCR layout did not expose reliable line items.")

    return ParsedSupplierStatement(
        statement_kind="trade_statement",
        is_financial=True,
        account_number=_extract_account_number(text),
        account_name=_extract_connacht_account_name(text),
        period_start=month_start,
        period_end=document.document_date,
        closing_balance=document.amount,
        invoice_references=invoice_references,
        payment_references=payment_references,
        note=" ".join(note_parts),
        entries=entries,
    )


def _normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = DATE_PATTERN.search(value)
    if not match:
        return None
    raw = match.group(1).replace("/", ".")
    try:
        day, month, year = raw.split(".")
        if len(year) == 2:
            year = f"20{year}"
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _extract_period_range(text: str) -> tuple[date | None, date | None]:
    matches = DATE_PATTERN.findall(text)
    if len(matches) < 2:
        return None, None

    for index in range(len(matches) - 1):
        left = _parse_date(matches[index])
        right = _parse_date(matches[index + 1])
        if left is None or right is None:
            continue
        if left <= right:
            return left, right
    return None, None


def _extract_account_number(text: str) -> str | None:
    lines = _normalized_lines(text)
    label_candidates = {"accountno", "accountnumber", "invoiceaddress", "acno"}
    for index, line in enumerate(lines):
        normalized = re.sub(r"[^a-z0-9]+", "", line.lower())
        if normalized not in label_candidates:
            continue
        for candidate in lines[index + 1 : index + 4]:
            if re.fullmatch(r"(?=.*\d)[A-Z0-9-]{4,}", candidate):
                return candidate

    match = re.search(r"\b((?=.*\d)[A-Z0-9-]{4,})\b", text)
    return match.group(1) if match else None


def _extract_account_name(text: str) -> str | None:
    lines = _normalized_lines(text)
    address_markers = (
        "Statement Address",
        "Invoice Address",
        "Delivery Address",
    )
    for marker in address_markers:
        if marker not in lines:
            continue
        index = lines.index(marker)
        block: list[str] = []
        for line in lines[index + 1 : index + 7]:
            if line in {"Correspondence Address", "Diageo Ireland", "Details", "Doc", "Date"}:
                break
            if not block and re.fullmatch(r"\d{4,}", line):
                continue
            block.append(line)
        if block:
            return ", ".join(block[:3])
    return None


def _extract_connacht_account_name(text: str) -> str | None:
    lines = _normalized_lines(text)
    statement_index = next((index for index, line in enumerate(lines) if line == "STATEMENT"), None)
    if statement_index is None:
        return _extract_account_name(text)
    block: list[str] = []
    for line in lines[statement_index + 1 : statement_index + 6]:
        normalized = line.lower().rstrip(":")
        if normalized in {"date", "reference", "your ref", "order no.", "type", "date"}:
            break
        block.append(line)
    return ", ".join(block[:3]) if block else _extract_account_name(text)


def _extract_value_after_label(text: str, label: str) -> Decimal | None:
    pattern = re.compile(rf"{re.escape(label)}\s+{DECIMAL_PATTERN.pattern}", re.IGNORECASE)
    match = pattern.search(text)
    if match:
        return _parse_decimal(match.group(1))
    return None


def _extract_opening_or_closing_balance(lines: list[str], prefix: str) -> Decimal | None:
    index = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    if index is None:
        return None
    for candidate in lines[index + 1 : index + 4]:
        value = _parse_decimal(candidate)
        if value is not None:
            return value
    return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.replace(",", "").strip()
    sign = -1 if normalized.endswith("-") else 1
    if normalized.endswith("-"):
        normalized = normalized[:-1]
    try:
        return Decimal(normalized) * sign
    except Exception:
        return None


def _is_invoice_statement_type(transaction_type: str | None) -> bool:
    normalized = (transaction_type or "").strip().lower()
    return normalized in {"invoice", "invoic", "cr.note", "crnote", "credit note", "credit"}


def _is_payment_statement_type(transaction_type: str | None) -> bool:
    normalized = (transaction_type or "").strip().lower()
    return normalized in {"payment", "paymnt", "receipt", "paymnt"}


def _looks_like_statement_reference(value: str) -> bool:
    compact = compact_profile_key(value)
    if len(compact) < 6:
        return False
    return bool(re.fullmatch(r"[a-z0-9]+", compact))


def _parse_connacht_statement_entries(lines: list[str]) -> list[ParsedSupplierStatementEntry]:
    date_indices = [
        index
        for index, line in enumerate(lines)
        if _parse_date(line) is not None
    ]
    chunks: list[list[str]] = []
    for position, start_index in enumerate(date_indices):
        end_index = date_indices[position + 1] if position + 1 < len(date_indices) else len(lines)
        chunk = lines[start_index:end_index]
        if chunk:
            chunks.append(chunk)

    entries: list[ParsedSupplierStatementEntry] = []
    seen_keys: set[tuple[str | None, str | None, str | None, str | None]] = set()
    for chunk in chunks:
        entry = _build_connacht_entry(chunk)
        if entry is None:
            continue
        key = (
            entry.event_date.isoformat() if entry.event_date else None,
            entry.reference,
            entry.transaction_type,
            str(entry.amount) if entry.amount is not None else None,
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entries.append(entry)

    entries.sort(
        key=lambda entry: (
            entry.event_date or date.max,
            entry.reference or "",
            entry.transaction_type or "",
        )
    )
    return entries


def _build_connacht_entry(chunk: list[str]) -> ParsedSupplierStatementEntry | None:
    chunk_text = " ".join(chunk)
    event_date = _parse_date(chunk[0])
    if event_date is None:
        return None

    transaction_type = None
    if "Cr.Note" in chunk_text or "CR.NOTE" in chunk_text:
        transaction_type = "Cr.Note"
    elif "Receipt" in chunk_text or "RECEIPT" in chunk_text:
        transaction_type = "Receipt"
    elif "Invoice" in chunk_text or "INVOICE" in chunk_text:
        transaction_type = "Invoice"

    if transaction_type is None:
        return None

    dd_match = re.search(r"\bDD-\d{2}-\d{2}\b", chunk_text)
    number_refs = [
        line
        for line in chunk[1:]
        if re.fullmatch(r"\d{4,6}", line)
    ]
    reference = dd_match.group(0) if dd_match else (number_refs[0] if number_refs else None)
    clearing_reference = None
    if transaction_type != "Receipt" and len(number_refs) >= 2:
        clearing_reference = number_refs[1]

    amounts = [_parse_decimal(value) for value in DECIMAL_PATTERN.findall(chunk_text)]
    amounts = [value for value in amounts if value is not None]
    amount = None
    if amounts:
        non_zero_amounts = [value for value in amounts if value != Decimal("0.00")]
        preferred = non_zero_amounts or amounts
        amount = preferred[0]
        if transaction_type == "Cr.Note":
            amount = abs(amount)

    return ParsedSupplierStatementEntry(
        event_date=event_date,
        reference=reference,
        transaction_type=transaction_type,
        clearing_reference=clearing_reference,
        amount=amount,
        raw_text=chunk_text,
    )


def _extract_statement_of_account_name(lines: list[str]) -> str | None:
    start_index = next((index for index, line in enumerate(lines) if line == "STATEMENT OF ACCOUNT"), None)
    date_index = next((index for index, line in enumerate(lines) if line.startswith("Date:")), None)
    if start_index is None or date_index is None or date_index <= start_index:
        return None

    block: list[str] = []
    for line in lines[start_index + 1 : date_index]:
        normalized = line.lower()
        if normalized.startswith("for attention of:"):
            continue
        if line == "Dear Sir/Madam,":
            break
        block.append(line)
    return ", ".join(block[:4]) if block else None


def _extract_statement_of_account_number(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if not (line.startswith("Customer Account No") or line == "Customer Number"):
            continue
        inline_match = re.search(r"Customer Account No:\s*([A-Z0-9-]{4,})", line, re.IGNORECASE)
        if inline_match:
            return inline_match.group(1)
        for candidate in lines[index + 1 : index + 3]:
            if re.fullmatch(r"[A-Z0-9-]{4,}", candidate):
                return candidate
    return None


def _extract_statement_of_account_period(lines: list[str]) -> tuple[date | None, date | None]:
    for index, line in enumerate(lines):
        if "Please find below your account statement with all items between" not in line:
            continue
        dates: list[date] = []
        for candidate in lines[index : index + 4]:
            for raw_match in DATE_PATTERN.findall(candidate):
                parsed = _parse_date(raw_match)
                if parsed is not None:
                    dates.append(parsed)
        if len(dates) >= 2:
            return dates[0], dates[1]
    return None, None


def _extract_statement_date(lines: list[str]) -> date | None:
    for index, line in enumerate(lines):
        if line.startswith("Date:") or line == "Statement Date":
            inline = _parse_date(line)
            if inline is not None:
                return inline
            for candidate in lines[index + 1 : index + 4]:
                parsed = _parse_date(candidate)
                if parsed is not None:
                    return parsed
    return None


def _parse_statement_of_account_entries(lines: list[str]) -> list[ParsedSupplierStatementEntry]:
    entries: list[ParsedSupplierStatementEntry] = []
    index = 0
    while index < len(lines):
        reference_number = lines[index]
        if not re.fullmatch(r"\d{8,12}", reference_number):
            index += 1
            continue

        descriptor = lines[index + 1] if index + 1 < len(lines) else ""
        parsed = _parse_statement_of_account_descriptor(descriptor)
        if parsed is None:
            index += 1
            continue
        transaction_type, document_reference = parsed

        doc_date = _parse_date(lines[index + 2]) if index + 2 < len(lines) else None
        due_date = _parse_date(lines[index + 3]) if index + 3 < len(lines) else None
        amounts = [
            _parse_decimal(lines[index + offset])
            for offset in range(4, 8)
            if index + offset < len(lines)
        ]
        amount_candidates = [value for value in amounts if value is not None]
        amount = None
        if amount_candidates:
            amount = abs(amount_candidates[0])

        entries.append(
            ParsedSupplierStatementEntry(
                event_date=doc_date,
                reference=document_reference or reference_number,
                transaction_type=transaction_type,
                due_date=due_date,
                clearing_reference=reference_number if document_reference else None,
                amount=amount,
                raw_text=" ".join(lines[index : min(index + 8, len(lines))]),
            )
        )
        index += 8

    return entries


def _parse_statement_of_account_columnar_entries(
    lines: list[str],
) -> list[ParsedSupplierStatementEntry]:
    header_index = next(
        (
            index
            for index in range(len(lines) - 1)
            if lines[index] == "Item" and lines[index + 1] == "Date"
        ),
        None,
    )
    if header_index is None:
        return []

    transaction_start = next(
        (
            index
            for index in range(header_index + 2, len(lines))
            if _normalize_statement_of_account_txn_type(lines[index]) is not None
        ),
        None,
    )
    if transaction_start is None:
        return []

    date_tokens = [
        candidate
        for candidate in lines[header_index + 2 : transaction_start]
        if _parse_date(candidate) is not None
    ]
    if len(date_tokens) < 2:
        return []

    transaction_codes: list[str] = []
    code_index = transaction_start
    while code_index < len(lines):
        normalized = _normalize_statement_of_account_txn_type(lines[code_index])
        if normalized is None:
            break
        transaction_codes.append(normalized)
        code_index += 1
    if not transaction_codes:
        return []

    document_refs: list[str] = []
    ref_index = code_index
    while ref_index < len(lines):
        value = lines[ref_index]
        if not re.fullmatch(r"\d{4,12}", value):
            break
        document_refs.append(value.lstrip("0") or value)
        ref_index += 1
    if not document_refs:
        return []

    amount_header_index = next(
        (
            index
            for index in range(ref_index, len(lines) - 1)
            if lines[index] == "Item" and lines[index + 1] == "Amount"
        ),
        None,
    )
    if amount_header_index is None:
        return []

    amount_values: list[Decimal] = []
    amount_index = amount_header_index + 2
    while amount_index < len(lines):
        value = _parse_decimal(lines[amount_index])
        if value is None:
            break
        amount_values.append(abs(value))
        amount_index += 1
    if not amount_values:
        return []

    entry_count = min(
        len(transaction_codes),
        len(document_refs),
        len(amount_values),
        len(date_tokens) // 2,
    )
    if entry_count <= 0:
        return []

    item_dates = date_tokens[:entry_count]
    due_dates = date_tokens[entry_count : entry_count * 2]
    entries: list[ParsedSupplierStatementEntry] = []
    for index in range(entry_count):
        event_date = _parse_date(item_dates[index]) if index < len(item_dates) else None
        due_date = _parse_date(due_dates[index]) if index < len(due_dates) else None
        transaction_type = transaction_codes[index]
        reference = document_refs[index]
        amount = amount_values[index]
        raw_parts = [part for part in [item_dates[index], due_dates[index] if index < len(due_dates) else None, transaction_type, reference, str(amount)] if part]
        entries.append(
            ParsedSupplierStatementEntry(
                event_date=event_date,
                due_date=due_date,
                reference=reference,
                transaction_type=transaction_type,
                amount=amount,
                raw_text=" ".join(raw_parts),
            )
        )

    return entries


def _looks_like_columnar_statement_of_account(lines: list[str]) -> bool:
    required_tokens = {"Statement Date", "TRN", "Document", "No", "Item", "Amount"}
    return all(token in lines for token in required_tokens) and any(
        _normalize_statement_of_account_txn_type(line) is not None for line in lines
    )


def _parse_statement_of_account_descriptor(value: str) -> tuple[str, str | None] | None:
    normalized = value.strip()
    if not normalized:
        return None

    invoice_match = re.fullmatch(r"(0?\d{8,12})\s+Invoice", normalized, re.IGNORECASE)
    if invoice_match:
        return "Invoice", invoice_match.group(1).lstrip("0") or invoice_match.group(1)

    credit_match = re.fullmatch(r"(0?\d{8,12})\s+Credit\s+Note", normalized, re.IGNORECASE)
    if credit_match:
        return "Cr.Note", credit_match.group(1).lstrip("0") or credit_match.group(1)

    lowered = normalized.lower()
    if lowered in ACCOUNT_STATEMENT_TXN_TYPES:
        if lowered == "payment":
            return "Payment", None
        if lowered == "receipt":
            return "Receipt", None
        if lowered in {"credit note", "creditnote"}:
            return "Cr.Note", None
        if lowered == "invoice":
            return "Invoice", None
    return None


def _normalize_statement_of_account_txn_type(value: str) -> str | None:
    normalized = re.sub(r"[^a-z]+", "", value.lower())
    if normalized in {"invoice", "inv"}:
        return "Invoice"
    if normalized in {"payment", "pay", "pmt"}:
        return "Payment"
    if normalized in {"receipt", "rec", "rct"}:
        return "Receipt"
    if normalized in {"creditnote", "credit", "crnote", "crn"}:
        return "Cr.Note"
    return None


PARSER_FAMILY_HANDLERS = {
    PARSER_FAMILY_DIAGEO_ERP: _parse_diageo_statement,
    PARSER_FAMILY_TRADE_STATEMENT: _parse_connacht_statement,
    PARSER_FAMILY_STATEMENT_OF_ACCOUNT: _parse_statement_of_account,
    PARSER_FAMILY_GENERIC_STATEMENT: _parse_generic_statement,
}
