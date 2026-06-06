from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import combinations
import uuid

from app.models import Document
from app.services.supplier_statement_parser import (
    ParsedSupplierStatement,
    ParsedSupplierStatementEntry,
    parse_supplier_statement,
)

LEDGER_ENTRY_INVOICE = "invoice"
LEDGER_ENTRY_CREDIT_NOTE = "credit_note"
LEDGER_ENTRY_PAYMENT = "payment"
LEDGER_ENTRY_OTHER = "other"

CHARGE_LEDGER_ENTRY_KINDS = {LEDGER_ENTRY_INVOICE, LEDGER_ENTRY_CREDIT_NOTE}
SETTLEMENT_LEDGER_ENTRY_KINDS = {
    LEDGER_ENTRY_INVOICE,
    LEDGER_ENTRY_CREDIT_NOTE,
    LEDGER_ENTRY_PAYMENT,
}


@dataclass(slots=True)
class ParsedLedgerEntry:
    document_id: uuid.UUID
    document_type: str
    supplier: str
    entry_kind: str
    event_date: date | None = None
    due_date: date | None = None
    reference: str | None = None
    related_reference: str | None = None
    amount: Decimal | None = None
    signed_amount: Decimal | None = None
    vat_amount: Decimal | None = None
    currency: str | None = None
    is_financial: bool = True
    statement_kind: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    raw_text: str | None = None


@dataclass(slots=True)
class ParsedDocumentLedger:
    document_id: uuid.UUID
    supplier: str
    document_type: str
    is_financial: bool
    source_text: str | None = None
    statement_kind: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    note: str | None = None
    entries: list[ParsedLedgerEntry] = field(default_factory=list)


@dataclass(slots=True)
class LedgerSettlement:
    payment_entry: ParsedLedgerEntry
    component_entries: list[ParsedLedgerEntry] = field(default_factory=list)
    net_amount: Decimal | None = None


def build_document_ledger(document: Document) -> ParsedDocumentLedger | None:
    if document.document_type == "statement":
        parsed_statement = parse_supplier_statement(document)
        if parsed_statement is None:
            return None
        return _build_statement_ledger(document, parsed_statement)

    entry_kind = _document_entry_kind(document.document_type)
    if entry_kind is None:
        return None
    if document.amount is None and entry_kind != LEDGER_ENTRY_OTHER:
        return None

    signed_amount = _signed_amount(entry_kind, document.amount)
    entry = ParsedLedgerEntry(
        document_id=document.id,
        document_type=document.document_type,
        supplier=document.supplier,
        entry_kind=entry_kind,
        event_date=document.document_date,
        reference=document.reference,
        amount=document.amount,
        signed_amount=signed_amount,
        vat_amount=document.vat_amount,
        currency=document.currency,
        is_financial=True,
    )
    return ParsedDocumentLedger(
        document_id=document.id,
        supplier=document.supplier,
        document_type=document.document_type,
        is_financial=True,
        source_text=document.extracted_text,
        entries=[entry],
    )


def build_document_ledgers(documents: list[Document]) -> list[ParsedDocumentLedger]:
    ledgers: list[ParsedDocumentLedger] = []
    for document in documents:
        ledger = build_document_ledger(document)
        if ledger is not None:
            ledgers.append(ledger)
    return ledgers


def flatten_ledger_entries(ledgers: list[ParsedDocumentLedger]) -> list[ParsedLedgerEntry]:
    return [entry for ledger in ledgers for entry in ledger.entries]


def find_matching_ledger_entries(
    *,
    entries: list[ParsedLedgerEntry],
    amount: Decimal | None,
    entry_kinds: set[str] | None = None,
) -> list[ParsedLedgerEntry]:
    if amount is None:
        return []
    allowed_kinds = entry_kinds or SETTLEMENT_LEDGER_ENTRY_KINDS
    return [
        entry
        for entry in entries
        if entry.amount is not None and entry.amount == amount and entry.entry_kind in allowed_kinds
    ]


def build_statement_settlements(ledger: ParsedDocumentLedger) -> list[LedgerSettlement]:
    if not ledger.is_financial:
        return []

    relevant_entries = [
        entry
        for entry in ledger.entries
        if entry.amount is not None and entry.entry_kind in SETTLEMENT_LEDGER_ENTRY_KINDS
    ]
    relevant_entries.sort(
        key=lambda entry: (
            entry.event_date or date.max,
            _entry_sort_rank(entry.entry_kind),
            entry.reference or "",
        )
    )

    backlog: list[ParsedLedgerEntry] = []
    settlements: list[LedgerSettlement] = []
    for entry in relevant_entries:
        if entry.entry_kind in CHARGE_LEDGER_ENTRY_KINDS:
            backlog.append(entry)
            continue
        if entry.entry_kind != LEDGER_ENTRY_PAYMENT:
            continue
        matched_components = _find_matching_charge_subset(backlog, entry.amount)
        if not matched_components:
            continue
        settlements.append(
            LedgerSettlement(
                payment_entry=entry,
                component_entries=matched_components,
                net_amount=_sum_signed_amounts(matched_components),
            )
        )
        matched_ids = {component.reference for component in matched_components}
        matched_identity = {
            (
                component.reference,
                component.related_reference,
                component.event_date.isoformat() if component.event_date else None,
                str(component.signed_amount) if component.signed_amount is not None else None,
            )
            for component in matched_components
        }
        backlog = [
            candidate
            for candidate in backlog
            if (
                candidate.reference not in matched_ids
                or (
                    candidate.reference,
                    candidate.related_reference,
                    candidate.event_date.isoformat() if candidate.event_date else None,
                    str(candidate.signed_amount) if candidate.signed_amount is not None else None,
                )
                not in matched_identity
            )
        ]

    return settlements


def find_matching_statement_settlements(
    *,
    ledgers: list[ParsedDocumentLedger],
    amount: Decimal | None,
) -> list[LedgerSettlement]:
    if amount is None:
        return []

    matches: list[LedgerSettlement] = []
    for ledger in ledgers:
        for settlement in build_statement_settlements(ledger):
            if settlement.payment_entry.amount == amount:
                matches.append(settlement)
    return matches


def _build_statement_ledger(
    document: Document,
    parsed_statement: ParsedSupplierStatement,
) -> ParsedDocumentLedger:
    entries = [
        _statement_entry_to_ledger_entry(document=document, parsed_statement=parsed_statement, entry=entry)
        for entry in parsed_statement.entries
    ]
    return ParsedDocumentLedger(
        document_id=document.id,
        supplier=document.supplier,
        document_type=document.document_type,
        is_financial=parsed_statement.is_financial,
        source_text=document.extracted_text,
        statement_kind=parsed_statement.statement_kind,
        account_number=parsed_statement.account_number,
        account_name=parsed_statement.account_name,
        period_start=parsed_statement.period_start,
        period_end=parsed_statement.period_end,
        note=parsed_statement.note,
        entries=entries,
    )


def _statement_entry_to_ledger_entry(
    *,
    document: Document,
    parsed_statement: ParsedSupplierStatement,
    entry: ParsedSupplierStatementEntry,
) -> ParsedLedgerEntry:
    entry_kind = _statement_entry_kind(entry.transaction_type)
    signed_amount = _signed_amount(entry_kind, entry.amount)
    return ParsedLedgerEntry(
        document_id=document.id,
        document_type=document.document_type,
        supplier=document.supplier,
        entry_kind=entry_kind,
        event_date=entry.event_date,
        due_date=entry.due_date,
        reference=entry.reference,
        related_reference=entry.clearing_reference,
        amount=entry.amount,
        signed_amount=signed_amount,
        currency=document.currency,
        is_financial=parsed_statement.is_financial,
        statement_kind=parsed_statement.statement_kind,
        account_number=parsed_statement.account_number,
        account_name=parsed_statement.account_name,
        raw_text=entry.raw_text,
    )


def _document_entry_kind(document_type: str | None) -> str | None:
    if document_type == "invoice":
        return LEDGER_ENTRY_INVOICE
    if document_type == "credit_note":
        return LEDGER_ENTRY_CREDIT_NOTE
    if document_type == "receipt":
        return LEDGER_ENTRY_PAYMENT
    return None


def _statement_entry_kind(transaction_type: str | None) -> str:
    normalized = (transaction_type or "").strip().lower()
    if normalized in {"invoice", "invoic", "inv"}:
        return LEDGER_ENTRY_INVOICE
    if normalized in {"cr.note", "crnote", "credit", "credit note", "crn"}:
        return LEDGER_ENTRY_CREDIT_NOTE
    if normalized in {"receipt", "rec", "rct", "paymnt", "payment", "pay", "pmt"}:
        return LEDGER_ENTRY_PAYMENT
    return LEDGER_ENTRY_OTHER


def _signed_amount(entry_kind: str, amount: Decimal | None) -> Decimal | None:
    if amount is None:
        return None
    if entry_kind == LEDGER_ENTRY_CREDIT_NOTE:
        return -abs(amount)
    return amount


def _entry_sort_rank(entry_kind: str) -> int:
    return {
        LEDGER_ENTRY_INVOICE: 0,
        LEDGER_ENTRY_CREDIT_NOTE: 1,
        LEDGER_ENTRY_PAYMENT: 2,
    }.get(entry_kind, 3)


def _sum_signed_amounts(entries: list[ParsedLedgerEntry]) -> Decimal | None:
    signed_amounts = [entry.signed_amount for entry in entries if entry.signed_amount is not None]
    if not signed_amounts:
        return None
    return sum(signed_amounts, Decimal("0"))


def _find_matching_charge_subset(
    backlog: list[ParsedLedgerEntry],
    payment_amount: Decimal | None,
) -> list[ParsedLedgerEntry]:
    if payment_amount is None or payment_amount <= 0:
        return []

    candidate_pool = backlog[-8:]
    if not candidate_pool:
        return []

    best_match: tuple[list[ParsedLedgerEntry], tuple[int, int, int]] | None = None
    max_size = min(len(candidate_pool), 5)
    for combo_size in range(1, max_size + 1):
        for combo in combinations(candidate_pool, combo_size):
            net_amount = _sum_signed_amounts(list(combo))
            if net_amount != payment_amount:
                continue

            most_recent_ordinal = max(
                entry.event_date.toordinal() if entry.event_date else 0 for entry in combo
            )
            oldest_ordinal = min(
                entry.event_date.toordinal() if entry.event_date else 0 for entry in combo
            )
            score = (-most_recent_ordinal, combo_size, -(most_recent_ordinal - oldest_ordinal))
            if best_match is None or score < best_match[1]:
                best_match = (list(combo), score)

    return best_match[0] if best_match is not None else []
