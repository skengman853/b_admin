from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import combinations
import uuid

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.attributes import NO_VALUE

from app.models import Document
from app.services.statement_arithmetic import amounts_match, classify_statement_row_kind
from app.services.supplier_statement_parser import (
    ParsedSupplierStatement,
    ParsedSupplierStatementEntry,
    parse_supplier_statement,
)

logger = logging.getLogger(__name__)

LEDGER_ENTRY_INVOICE = "invoice"
LEDGER_ENTRY_CREDIT_NOTE = "credit_note"
LEDGER_ENTRY_PAYMENT = "payment"
LEDGER_ENTRY_DISCOUNT = "discount"
LEDGER_ENTRY_OTHER = "other"

# Charges that can be components of a settlement group. Discounts net inside
# a group (prompt-payment terms), but are never direct bank-amount matches.
CHARGE_LEDGER_ENTRY_KINDS = {LEDGER_ENTRY_INVOICE, LEDGER_ENTRY_CREDIT_NOTE, LEDGER_ENTRY_DISCOUNT}
SETTLEMENT_LEDGER_ENTRY_KINDS = {
    LEDGER_ENTRY_INVOICE,
    LEDGER_ENTRY_CREDIT_NOTE,
    LEDGER_ENTRY_PAYMENT,
}
SETTLEMENT_GROUP_ENTRY_KINDS = SETTLEMENT_LEDGER_ENTRY_KINDS | {LEDGER_ENTRY_DISCOUNT}


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
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    total_due: Decimal | None = None
    settlement_discount_total: Decimal | None = None
    note: str | None = None
    entries: list[ParsedLedgerEntry] = field(default_factory=list)


@dataclass(slots=True)
class LedgerSettlement:
    payment_entry: ParsedLedgerEntry
    component_entries: list[ParsedLedgerEntry] = field(default_factory=list)
    net_amount: Decimal | None = None


def build_document_ledger(
    document: Document,
    *,
    allow_parse_fallback: bool | None = None,
) -> ParsedDocumentLedger | None:
    """Build a ledger, preferring persisted financial facts/rows.

    ``allow_parse_fallback`` controls what happens when no persisted state is
    available for a statement:
    - ``True``: page-time parse silently (writers and transient documents).
    - ``False``: strict; return None.
    - ``None`` (default): parse, but log the drift signal — persisted rows are
      the source of truth at read time, so a fallback here means either the
      call site forgot to eager-load financial state or an extracted document
      was never synced.
    """
    persisted_ledger = _build_persisted_document_ledger(document)
    if persisted_ledger is not None:
        return persisted_ledger

    if document.document_type == "statement":
        if allow_parse_fallback is False:
            return None
        if allow_parse_fallback is None:
            _log_parse_fallback_drift(document)
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


def build_document_ledgers(
    documents: list[Document],
    *,
    allow_parse_fallback: bool | None = None,
) -> list[ParsedDocumentLedger]:
    ledgers: list[ParsedDocumentLedger] = []
    for document in documents:
        ledger = build_document_ledger(document, allow_parse_fallback=allow_parse_fallback)
        if ledger is not None:
            ledgers.append(ledger)
    return ledgers


def _log_parse_fallback_drift(document: Document) -> None:
    state = sa_inspect(document)
    rows_loaded = state.attrs.financial_rows.loaded_value is not NO_VALUE
    fact_loaded = state.attrs.financial_fact.loaded_value is not NO_VALUE
    if not rows_loaded or not fact_loaded:
        logger.warning(
            "statement %s (%s): financial state not eager-loaded; using page-time parse. "
            "Load Document.financial_fact and Document.financial_rows at the call site so "
            "persisted rows stay the source of truth.",
            document.id,
            document.supplier,
        )
    elif document.extraction_status in {"extracted", "reviewed"}:
        logger.warning(
            "statement %s (%s) is %s but has no persisted financial state; using page-time parse. "
            "Re-run extraction or the financial-state backfill.",
            document.id,
            document.supplier,
            document.extraction_status,
        )


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
        if amounts_match(entry.amount, amount) and entry.entry_kind in allowed_kinds
    ]


def build_statement_settlements(ledger: ParsedDocumentLedger) -> list[LedgerSettlement]:
    if not ledger.is_financial:
        return []

    relevant_entries = [
        entry
        for entry in ledger.entries
        if entry.amount is not None and entry.entry_kind in SETTLEMENT_GROUP_ENTRY_KINDS
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
            if amounts_match(settlement.payment_entry.amount, amount):
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
        opening_balance=parsed_statement.opening_balance,
        closing_balance=parsed_statement.closing_balance,
        total_due=parsed_statement.total_due,
        settlement_discount_total=parsed_statement.settlement_discount_total,
        note=parsed_statement.note,
        entries=entries,
    )


def _build_persisted_document_ledger(document: Document) -> ParsedDocumentLedger | None:
    state = sa_inspect(document)
    fact_attr = state.attrs.financial_fact
    rows_attr = state.attrs.financial_rows
    if fact_attr.loaded_value is NO_VALUE or rows_attr.loaded_value is NO_VALUE:
        return None

    fact = fact_attr.loaded_value
    if fact is None:
        return None

    persisted_rows = sorted(rows_attr.loaded_value or [], key=lambda row: row.row_index)
    entries = [
        ParsedLedgerEntry(
            document_id=document.id,
            document_type=document.document_type,
            supplier=document.supplier,
            entry_kind=row.row_type,
            event_date=row.event_date,
            due_date=row.due_date,
            reference=row.reference,
            related_reference=row.clearing_reference,
            amount=row.amount,
            signed_amount=row.signed_amount,
            vat_amount=fact.vat_amount if len(persisted_rows) == 1 else None,
            currency=row.currency or fact.currency,
            is_financial=row.is_financial,
            statement_kind=fact.statement_kind,
            account_number=fact.account_number,
            account_name=fact.account_name,
            raw_text=row.raw_text,
        )
        for row in persisted_rows
    ]

    if not entries:
        entry_kind = _document_entry_kind(fact.document_type)
        if entry_kind is not None and fact.amount is not None:
            entries.append(
                ParsedLedgerEntry(
                    document_id=document.id,
                    document_type=document.document_type,
                    supplier=document.supplier,
                    entry_kind=entry_kind,
                    event_date=fact.document_date,
                    reference=fact.reference,
                    amount=fact.amount,
                    signed_amount=_signed_amount(entry_kind, fact.amount),
                    vat_amount=fact.vat_amount,
                    currency=fact.currency,
                    is_financial=fact.is_financial,
                    statement_kind=fact.statement_kind,
                    account_number=fact.account_number,
                    account_name=fact.account_name,
                )
            )

    return ParsedDocumentLedger(
        document_id=document.id,
        supplier=document.supplier,
        document_type=document.document_type,
        is_financial=fact.is_financial,
        source_text=document.extracted_text,
        statement_kind=fact.statement_kind,
        account_number=fact.account_number,
        account_name=fact.account_name,
        period_start=fact.period_start,
        period_end=fact.period_end,
        opening_balance=fact.opening_balance,
        closing_balance=fact.closing_balance,
        total_due=fact.total_due,
        settlement_discount_total=fact.settlement_discount_total,
        entries=entries,
    )


def _statement_entry_to_ledger_entry(
    *,
    document: Document,
    parsed_statement: ParsedSupplierStatement,
    entry: ParsedSupplierStatementEntry,
) -> ParsedLedgerEntry:
    entry_kind = _statement_entry_kind(entry.transaction_type, reference=entry.reference)
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


def _statement_entry_kind(transaction_type: str | None, *, reference: str | None = None) -> str:
    return classify_statement_row_kind(transaction_type, reference=reference)


def _signed_amount(entry_kind: str, amount: Decimal | None) -> Decimal | None:
    if amount is None:
        return None
    if entry_kind in {LEDGER_ENTRY_CREDIT_NOTE, LEDGER_ENTRY_DISCOUNT}:
        return -abs(amount)
    return amount


def _entry_sort_rank(entry_kind: str) -> int:
    return {
        LEDGER_ENTRY_INVOICE: 0,
        LEDGER_ENTRY_CREDIT_NOTE: 1,
        LEDGER_ENTRY_DISCOUNT: 2,
        LEDGER_ENTRY_PAYMENT: 3,
    }.get(entry_kind, 4)


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
            if not amounts_match(net_amount, payment_amount):
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
