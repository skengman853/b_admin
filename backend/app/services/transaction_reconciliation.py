from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
import re
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Transaction, TransactionDocumentLink
from app.services.document_ledger import (
    CHARGE_LEDGER_ENTRY_KINDS,
    LEDGER_ENTRY_CREDIT_NOTE,
    LEDGER_ENTRY_INVOICE,
    LEDGER_ENTRY_PAYMENT,
    LedgerSettlement,
    ParsedDocumentLedger,
    ParsedLedgerEntry,
    build_document_ledgers,
    build_statement_settlements,
    find_matching_ledger_entries,
)
from app.services.supplier_profiles import (
    DOCUMENT_METADATA_PUB_ALIASES,
    DOCUMENT_RECIPIENT_PUB_ALIASES,
    DOCUMENT_STATEMENT_PUB_ALIASES,
    TRANSACTION_PUB_ALIASES,
    build_supplier_lookup_keys,
    compact_profile_key,
    match_supplier_profile,
)

AUTO_EXACT_LINK_NOTE = "auto_exact_reference_note_match"
EXACT_REFERENCE_REASON = "Reference found in VAT-book annotation notes"
VALID_RECONCILIATION_STATUSES = {"matched", "partial", "suggested", "unmatched"}
DEFAULT_REVIEW_QUEUE_STATUSES = ("partial", "suggested", "unmatched")
RESOLVED_TRANSACTION_REVIEW_STATUSES = {"linked", "supporting_docs_only", "no_document_expected"}
VALID_RESOLUTION_BUCKETS = {
    "confirm_match",
    "complete_partial_match",
    "review_supporting_docs",
    "awaiting_document",
    "no_document_expected",
    "needs_matcher_improvement",
}
BANK_STATEMENT_SOURCE_TYPE = "bank_statement"
BANK_STATEMENT_COUNTERPARTY_PREFIX_PATTERN = re.compile(
    r"^(?:\*?(?:inet|mobi|pos|visa|mc|card)\s+|(?:d/d|dd|vdp|vdc)\s*[- ]*)",
    re.IGNORECASE,
)
DOCUMENT_RECIPIENT_LABELS = ("invoice to", "bill to", "billed to", "account name")
DOCUMENT_STATEMENT_ADDRESS_LABELS = (
    "statement address",
    "invoice address",
    "delivery address",
    "account address",
    "to",
)
GENERIC_SUPPLIER_TOKENS = {
    "accounts",
    "attached",
    "billing",
    "business",
    "careys",
    "copy",
    "credit",
    "debit",
    "from",
    "info",
    "invoice",
    "invoices",
    "irela",
    "ireland",
    "limited",
    "ltd",
    "note",
    "orders",
    "payment",
    "payments",
    "statement",
    "services",
    "service",
    "the",
}
NO_DOCUMENT_EXPECTED_PATTERNS = (
    re.compile(r"\bbank\s+(?:charge|fee|interest)\b", re.IGNORECASE),
    re.compile(r"\b(?:charge|charges|interest|commission|stamp duty)\b", re.IGNORECASE),
    re.compile(r"\b(?:atm|cash withdrawal)\b", re.IGNORECASE),
)
INDIVIDUAL_PAYMENT_PREFIX_PATTERN = re.compile(r"^\*(?:INET|MOBI)\b", re.IGNORECASE)


@dataclass(slots=True)
class ReconciliationDocumentMatch:
    document_id: uuid.UUID
    document_type: str
    supplier: str
    reference: str | None
    document_date: date | None
    amount: Decimal | None
    vat_amount: Decimal | None
    score: float | None
    reason: str


@dataclass(slots=True)
class ReconciliationTransactionItem:
    transaction_id: uuid.UUID
    source_type: str
    row_number: int
    pub: str | None
    transaction_date: date | None
    description1: str | None
    description2: str | None
    category: str | None
    transaction_type: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    annotation_types: list[str] = field(default_factory=list)
    annotation_notes: list[str] = field(default_factory=list)
    has_linked_annotation: bool = False
    status: str = "unmatched"
    analysis_note: str | None = None
    resolution_bucket: str = "awaiting_document"
    recommended_review_status: str | None = "awaiting_document"
    resolution_reason: str | None = None
    exact_matches: list[ReconciliationDocumentMatch] = field(default_factory=list)
    suggested_matches: list[ReconciliationDocumentMatch] = field(default_factory=list)
    supporting_matches: list[ReconciliationDocumentMatch] = field(default_factory=list)


@dataclass(slots=True)
class ReconciliationReport:
    month: str
    pub: str | None
    total_transactions: int
    expense_transactions: int
    annotated_transactions: int
    linked_transactions: int
    matched_transactions: int
    partial_transactions: int
    suggested_transactions: int
    unmatched_transactions: int
    invoice_documents_in_month: int
    unmatched_invoice_documents: int
    resolution_bucket_counts: dict[str, int] = field(default_factory=dict)
    transactions: list[ReconciliationTransactionItem] = field(default_factory=list)
    unmatched_documents: list[ReconciliationDocumentMatch] = field(default_factory=list)


@dataclass(slots=True)
class TransactionReviewQueue:
    month: str
    pub: str | None
    annotated_only: bool
    statuses: list[str]
    total: int
    page: int
    pages: int
    matched_transactions: int
    partial_transactions: int
    suggested_transactions: int
    unmatched_transactions: int
    resolution_bucket_counts: dict[str, int] = field(default_factory=dict)
    transactions: list[ReconciliationTransactionItem] = field(default_factory=list)


@dataclass(slots=True)
class ReconciliationFlowDocument:
    document_id: uuid.UUID
    supplier: str
    document_type: str
    reference: str | None = None
    document_date: date | None = None
    amount: Decimal | None = None
    vat_amount: Decimal | None = None
    score: float | None = None
    role: str | None = None
    reason: str | None = None
    statement_kind: str | None = None
    is_financial: bool | None = None
    invoice_reference_count: int = 0
    payment_reference_count: int = 0
    credit_reference_count: int = 0
    settlement_count: int = 0


@dataclass(slots=True)
class ReconciliationFlowSettlement:
    source_document_id: uuid.UUID
    source_supplier: str
    source_reference: str | None = None
    source_document_date: date | None = None
    statement_kind: str | None = None
    payment_entry: ParsedLedgerEntry | None = None
    component_entries: list[ParsedLedgerEntry] = field(default_factory=list)
    net_amount: Decimal | None = None
    matches_transaction_amount: bool = False


@dataclass(slots=True)
class ReconciliationFlowStage:
    key: str
    title: str
    status: str
    summary: str
    items: list[str] = field(default_factory=list)
    documents: list[ReconciliationFlowDocument] = field(default_factory=list)


@dataclass(slots=True)
class ReconciliationFlow:
    flow_type: str
    supplier_label: str | None
    bank_counterparty: str | None
    next_step: str
    stages: list[ReconciliationFlowStage] = field(default_factory=list)
    settlements: list[ReconciliationFlowSettlement] = field(default_factory=list)


def month_bounds(month: str) -> tuple[date, date]:
    year, month_number = int(month[:4]), int(month[5:7])
    start = date(year, month_number, 1)
    end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)
    return start, end


async def build_reconciliation_report(
    *,
    db: AsyncSession,
    user_id,
    month: str,
    source_type: str | None = None,
    pub: str | None = None,
    limit: int = 100,
    annotated_only: bool = True,
    persist_exact_matches: bool = False,
) -> ReconciliationReport:
    start, end = month_bounds(month)

    transaction_query = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date < end,
    )
    if source_type:
        transaction_query = transaction_query.where(Transaction.source_type == source_type)
    if pub:
        transaction_query = transaction_query.where(Transaction.pub == pub)

    transaction_result = await db.execute(
        transaction_query.order_by(Transaction.transaction_date.asc(), Transaction.row_number.asc())
    )
    all_transactions = list(transaction_result.scalars().all())

    expense_transactions = [
        transaction
        for transaction in all_transactions
        if transaction.debit_amount is not None and transaction.debit_amount > 0
    ]
    annotated_transactions = [
        transaction for transaction in expense_transactions if transaction.annotation_notes
    ]
    linked_transactions = [
        transaction for transaction in expense_transactions if transaction.has_linked_annotation
    ]

    report_transactions = annotated_transactions if annotated_only else expense_transactions

    candidate_documents = await load_candidate_documents_for_period(
        db=db,
        user_id=user_id,
        start=start,
        end=end,
    )
    supporting_documents = await load_supporting_documents_for_period(
        db=db,
        user_id=user_id,
        start=start,
        end=end,
    )
    candidate_ledgers = build_document_ledgers(candidate_documents)
    supporting_ledgers = build_document_ledgers(supporting_documents)

    month_document_result = await db.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.document_type == "invoice",
            Document.document_date >= start,
            Document.document_date < end,
        )
    )
    month_documents = [
        document
        for document in month_document_result.scalars().all()
        if _document_is_matchable(document)
    ]

    matched_document_ids: set[uuid.UUID] = set()
    suggested_document_ids: set[uuid.UUID] = set()
    matched_transactions = 0
    partial_transactions = 0
    suggested_transactions = 0
    unmatched_transactions = 0
    report_items: list[ReconciliationTransactionItem] = []
    exact_matches_by_transaction: dict[uuid.UUID, list[ReconciliationDocumentMatch]] = {}
    resolution_bucket_counts = {bucket: 0 for bucket in VALID_RESOLUTION_BUCKETS}

    for transaction in report_transactions:
        item = build_transaction_reconciliation_item(
            transaction=transaction,
            documents=candidate_documents,
            supporting_documents=supporting_documents,
            document_ledgers=candidate_ledgers,
            supporting_document_ledgers=supporting_ledgers,
        )
        exact_matches_by_transaction[transaction.id] = item.exact_matches
        matched_document_ids.update(match.document_id for match in item.exact_matches)
        suggested_document_ids.update(match.document_id for match in item.suggested_matches)

        if item.status == "matched":
            matched_transactions += 1
        elif item.status == "partial":
            partial_transactions += 1
        elif item.status == "suggested":
            suggested_transactions += 1
        else:
            unmatched_transactions += 1

        report_items.append(item)
        resolution_bucket_counts[item.resolution_bucket] = (
            resolution_bucket_counts.get(item.resolution_bucket, 0) + 1
        )

    if persist_exact_matches:
        await sync_exact_transaction_document_links(
            db=db,
            user_id=user_id,
            exact_matches_by_transaction=exact_matches_by_transaction,
        )

    sorted_report_items = sorted(
        report_items,
        key=lambda item: (
            _status_rank(item.status),
            -len(item.exact_matches),
            -_max_score(item.suggested_matches),
            -_max_score(item.supporting_matches),
            item.transaction_date or date.max,
            item.row_number,
        ),
    )

    unmatched_documents = [
        ReconciliationDocumentMatch(
            document_id=document.id,
            document_type=document.document_type,
            supplier=document.supplier,
            reference=document.reference,
            document_date=document.document_date,
            amount=document.amount,
            vat_amount=document.vat_amount,
            score=None,
            reason="No transaction report match found for this invoice in the selected month",
        )
        for document in month_documents
        if document.id not in matched_document_ids and document.id not in suggested_document_ids
    ]

    return ReconciliationReport(
        month=month,
        pub=pub,
        total_transactions=len(all_transactions),
        expense_transactions=len(expense_transactions),
        annotated_transactions=len(annotated_transactions),
        linked_transactions=len(linked_transactions),
        matched_transactions=matched_transactions,
        partial_transactions=partial_transactions,
        suggested_transactions=suggested_transactions,
        unmatched_transactions=unmatched_transactions,
        invoice_documents_in_month=len(month_documents),
        unmatched_invoice_documents=len(unmatched_documents),
        resolution_bucket_counts=resolution_bucket_counts,
        transactions=sorted_report_items[:limit],
        unmatched_documents=unmatched_documents[:limit],
    )


async def build_transaction_review_queue(
    *,
    db: AsyncSession,
    user_id,
    month: str,
    source_type: str | None = None,
    pub: str | None = None,
    statuses: list[str] | None = None,
    resolution_buckets: list[str] | None = None,
    review_statuses: list[str] | None = None,
    annotated_only: bool = True,
    persist_exact_matches: bool = False,
    page: int = 1,
    limit: int = 50,
) -> TransactionReviewQueue:
    start, end = month_bounds(month)
    requested_statuses = statuses or list(DEFAULT_REVIEW_QUEUE_STATUSES)
    normalized_statuses = [status for status in requested_statuses if status in VALID_RECONCILIATION_STATUSES]
    if not normalized_statuses:
        normalized_statuses = list(DEFAULT_REVIEW_QUEUE_STATUSES)

    transaction_query = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date < end,
    )
    if source_type:
        transaction_query = transaction_query.where(Transaction.source_type == source_type)
    if pub:
        transaction_query = transaction_query.where(Transaction.pub == pub)

    transaction_result = await db.execute(
        transaction_query.order_by(Transaction.transaction_date.asc(), Transaction.row_number.asc())
    )
    all_transactions = list(transaction_result.scalars().all())
    expense_transactions = [
        transaction
        for transaction in all_transactions
        if transaction.debit_amount is not None and transaction.debit_amount > 0
    ]
    review_transactions = (
        [transaction for transaction in expense_transactions if transaction.annotation_notes]
        if annotated_only
        else expense_transactions
    )

    candidate_documents = await load_candidate_documents_for_period(
        db=db,
        user_id=user_id,
        start=start,
        end=end,
    )
    supporting_documents = await load_supporting_documents_for_period(
        db=db,
        user_id=user_id,
        start=start,
        end=end,
    )
    candidate_ledgers = build_document_ledgers(candidate_documents)
    supporting_ledgers = build_document_ledgers(supporting_documents)

    items: list[ReconciliationTransactionItem] = [
        build_transaction_reconciliation_item(
            transaction=transaction,
            documents=candidate_documents,
            supporting_documents=supporting_documents,
            document_ledgers=candidate_ledgers,
            supporting_document_ledgers=supporting_ledgers,
        )
        for transaction in review_transactions
    ]

    exact_matches_by_transaction = {
        item.transaction_id: item.exact_matches
        for item in items
        if item.exact_matches
    }
    if persist_exact_matches and exact_matches_by_transaction:
        await sync_exact_transaction_document_links(
            db=db,
            user_id=user_id,
            exact_matches_by_transaction=exact_matches_by_transaction,
        )

    matched_count = sum(1 for item in items if item.status == "matched")
    partial_count = sum(1 for item in items if item.status == "partial")
    suggested_count = sum(1 for item in items if item.status == "suggested")
    unmatched_count = sum(1 for item in items if item.status == "unmatched")
    transaction_by_id = {transaction.id: transaction for transaction in review_transactions}
    filtered_items = [
        item
        for item in items
        if item.status in normalized_statuses
        and (resolution_buckets is None or item.resolution_bucket in resolution_buckets)
        and (
            (transaction_by_id[item.transaction_id].review_status in review_statuses)
            if review_statuses is not None
            else transaction_by_id[item.transaction_id].review_status not in RESOLVED_TRANSACTION_REVIEW_STATUSES
        )
    ]
    resolution_bucket_counts = {
        bucket: sum(1 for item in filtered_items if item.resolution_bucket == bucket)
        for bucket in VALID_RESOLUTION_BUCKETS
    }
    filtered_items.sort(
        key=lambda item: (
            _status_rank(item.status),
            -len(item.exact_matches),
            -_max_score(item.suggested_matches),
            -_max_score(item.supporting_matches),
            item.transaction_date or date.max,
            item.row_number,
        ),
    )

    total = len(filtered_items)
    start_index = (page - 1) * limit
    page_items = filtered_items[start_index:start_index + limit]

    return TransactionReviewQueue(
        month=month,
        pub=pub,
        annotated_only=annotated_only,
        statuses=normalized_statuses,
        total=total,
        page=page,
        pages=((total - 1) // limit + 1) if total else 1,
        matched_transactions=matched_count,
        partial_transactions=partial_count,
        suggested_transactions=suggested_count,
        unmatched_transactions=unmatched_count,
        resolution_bucket_counts=resolution_bucket_counts,
        transactions=page_items,
    )


async def load_candidate_documents_for_period(
    *,
    db: AsyncSession,
    user_id,
    start: date,
    end: date,
) -> list[Document]:
    candidate_document_result = await db.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.document_type == "invoice",
            Document.document_date >= start - timedelta(days=90),
            Document.document_date < end + timedelta(days=31),
        )
    )
    return [
        document
        for document in candidate_document_result.scalars().all()
        if _document_is_matchable(document)
    ]


async def load_supporting_documents_for_period(
    *,
    db: AsyncSession,
    user_id,
    start: date,
    end: date,
) -> list[Document]:
    supporting_document_result = await db.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.document_date >= start - timedelta(days=90),
            Document.document_date < end + timedelta(days=31),
            Document.document_type != "invoice",
        )
    )
    return [
        document
        for document in supporting_document_result.scalars().all()
        if document.extraction_status != "split"
    ]


async def load_candidate_documents_for_transaction(
    *,
    db: AsyncSession,
    user_id,
    transaction: Transaction,
) -> list[Document]:
    transaction_date = transaction.transaction_date or date.today()
    start = transaction_date.replace(day=1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return await load_candidate_documents_for_period(
        db=db,
        user_id=user_id,
        start=start,
        end=end,
    )


async def load_supporting_documents_for_transaction(
    *,
    db: AsyncSession,
    user_id,
    transaction: Transaction,
) -> list[Document]:
    transaction_date = transaction.transaction_date or date.today()
    start = transaction_date.replace(day=1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return await load_supporting_documents_for_period(
        db=db,
        user_id=user_id,
        start=start,
        end=end,
    )


async def build_transaction_reconciliation_item_from_db(
    *,
    db: AsyncSession,
    user_id,
    transaction: Transaction,
) -> ReconciliationTransactionItem:
    candidate_documents = await load_candidate_documents_for_transaction(
        db=db,
        user_id=user_id,
        transaction=transaction,
    )
    supporting_documents = await load_supporting_documents_for_transaction(
        db=db,
        user_id=user_id,
        transaction=transaction,
    )
    candidate_ledgers = build_document_ledgers(candidate_documents)
    supporting_ledgers = build_document_ledgers(supporting_documents)
    return build_transaction_reconciliation_item(
        transaction=transaction,
        documents=candidate_documents,
        supporting_documents=supporting_documents,
        document_ledgers=candidate_ledgers,
        supporting_document_ledgers=supporting_ledgers,
    )


def build_transaction_reconciliation_flow(
    *,
    transaction: Transaction,
    analysis: ReconciliationTransactionItem,
    invoice_documents: list[Document],
    supporting_documents: list[Document],
    invoice_ledgers: list[ParsedDocumentLedger],
    supporting_ledgers: list[ParsedDocumentLedger],
    persisted_links: list[TransactionDocumentLink] | None = None,
) -> ReconciliationFlow:
    bank_counterparty = _clean_bank_statement_counterparty(transaction.description1) or transaction.description1
    supplier_label = _derive_flow_supplier_label(
        transaction=transaction,
        analysis=analysis,
        bank_counterparty=bank_counterparty,
    )
    persisted_links = persisted_links or []
    support_doc_by_id = {document.id: document for document in supporting_documents}
    invoice_doc_by_id = {document.id: document for document in invoice_documents}
    support_ledger_by_id = {ledger.document_id: ledger for ledger in supporting_ledgers}
    invoice_ledger_by_id = {ledger.document_id: ledger for ledger in invoice_ledgers}

    related_statement_ledgers = _collect_related_statement_ledgers(
        transaction=transaction,
        analysis=analysis,
        supporting_documents=supporting_documents,
        supporting_ledgers=supporting_ledgers,
        persisted_links=persisted_links,
        invoice_ledgers=invoice_ledgers,
    )
    statement_documents: list[ReconciliationFlowDocument] = []
    settlements: list[ReconciliationFlowSettlement] = []
    all_statement_invoice_refs: list[str] = []
    all_statement_credit_refs: list[str] = []
    all_statement_payment_refs: list[str] = []
    statements_missing_amounts = False
    non_financial_support_count = 0

    for ledger in related_statement_ledgers:
        document = support_doc_by_id.get(ledger.document_id)
        if document is None:
            continue
        statement_settlements = build_statement_settlements(ledger)
        matching_settlements = [
            settlement
            for settlement in statement_settlements
            if transaction.debit_amount is not None and settlement.payment_entry.amount == transaction.debit_amount
        ]
        ledger_invoice_refs = _ordered_unique(
            [
                entry.reference
                for entry in ledger.entries
                if entry.entry_kind == LEDGER_ENTRY_INVOICE and entry.reference
            ]
        )
        ledger_credit_refs = _ordered_unique(
            [
                entry.reference or entry.related_reference
                for entry in ledger.entries
                if entry.entry_kind == LEDGER_ENTRY_CREDIT_NOTE and (entry.reference or entry.related_reference)
            ]
        )
        ledger_payment_refs = _ordered_unique(
            [
                entry.reference
                for entry in ledger.entries
                if entry.entry_kind == LEDGER_ENTRY_PAYMENT and entry.reference
            ]
        )
        if any(
            entry.entry_kind in {LEDGER_ENTRY_INVOICE, LEDGER_ENTRY_PAYMENT, LEDGER_ENTRY_CREDIT_NOTE}
            and entry.reference
            and entry.amount is None
            for entry in ledger.entries
        ):
            statements_missing_amounts = True
        if not ledger.is_financial:
            non_financial_support_count += 1

        all_statement_invoice_refs.extend(ledger_invoice_refs)
        all_statement_credit_refs.extend(ledger_credit_refs)
        all_statement_payment_refs.extend(ledger_payment_refs)

        statement_documents.append(
            ReconciliationFlowDocument(
                document_id=document.id,
                supplier=document.supplier,
                document_type=document.document_type,
                reference=document.reference,
                document_date=document.document_date,
                amount=document.amount,
                vat_amount=document.vat_amount,
                score=_document_score_from_analysis(document.id, analysis, persisted_links),
                role="statement_support",
                reason=_document_reason_from_analysis(document.id, analysis, persisted_links),
                statement_kind=ledger.statement_kind,
                is_financial=ledger.is_financial,
                invoice_reference_count=len(ledger_invoice_refs),
                payment_reference_count=len(ledger_payment_refs),
                credit_reference_count=len(ledger_credit_refs),
                settlement_count=len(matching_settlements),
            )
        )

        for settlement in matching_settlements:
            settlements.append(
                ReconciliationFlowSettlement(
                    source_document_id=document.id,
                    source_supplier=document.supplier,
                    source_reference=document.reference,
                    source_document_date=document.document_date,
                    statement_kind=ledger.statement_kind,
                    payment_entry=settlement.payment_entry,
                    component_entries=list(settlement.component_entries),
                    net_amount=settlement.net_amount,
                    matches_transaction_amount=True,
                )
            )

    statement_invoice_refs = _ordered_unique(all_statement_invoice_refs)
    statement_credit_refs = _ordered_unique(all_statement_credit_refs)
    statement_payment_refs = _ordered_unique(all_statement_payment_refs)

    component_documents = _build_flow_component_documents(
        transaction=transaction,
        analysis=analysis,
        invoice_documents=invoice_documents,
        invoice_doc_by_id=invoice_doc_by_id,
        invoice_ledger_by_id=invoice_ledger_by_id,
        supporting_documents=supporting_documents,
        supporting_ledgers=supporting_ledgers,
        statement_invoice_refs=statement_invoice_refs,
        statement_credit_refs=statement_credit_refs,
    )
    found_component_refs = {
        document.reference
        for document in component_documents
        if document.reference
    }
    missing_invoice_refs = [
        reference for reference in statement_invoice_refs if reference not in found_component_refs
    ]
    missing_credit_refs = [
        reference for reference in statement_credit_refs if reference not in found_component_refs
    ]

    supplier_stage = ReconciliationFlowStage(
        key="supplier",
        title="Supplier",
        status="ready" if supplier_label or bank_counterparty else "missing",
        summary=_build_supplier_stage_summary(
            transaction=transaction,
            supplier_label=supplier_label,
            bank_counterparty=bank_counterparty,
        ),
        items=[
            item
            for item in [
                f"Bank payee: {bank_counterparty}" if bank_counterparty else None,
                f"Expected supplier hint: {transaction.expected_supplier}" if transaction.expected_supplier else None,
                f"Pub: {transaction.pub}" if transaction.pub else None,
            ]
            if item
        ],
    )

    statement_stage_status = "missing"
    if settlements:
        statement_stage_status = "ready"
    elif statement_documents:
        statement_stage_status = "partial"

    statement_items: list[str] = []
    if statement_invoice_refs:
        statement_items.append(f"Statement invoice refs found: {', '.join(statement_invoice_refs[:8])}")
    if statement_credit_refs:
        statement_items.append(f"Statement credit refs found: {', '.join(statement_credit_refs[:8])}")
    if statement_payment_refs:
        statement_items.append(f"Statement payment refs found: {', '.join(statement_payment_refs[:8])}")
    if non_financial_support_count:
        statement_items.append(
            f"{non_financial_support_count} non-financial support document(s) were kept as context only"
        )
    if statements_missing_amounts and not settlements:
        statement_items.append(
            "Statement refs were extracted, but some statement line amounts are still missing, so the payment cannot be grouped automatically yet"
        )
    if not statement_items and statement_documents:
        statement_items.append("Statement support exists, but the current docs do not yet produce a full payment group")

    statement_stage = ReconciliationFlowStage(
        key="statement",
        title="Statement",
        status=statement_stage_status,
        summary=_build_statement_stage_summary(
            statement_documents=statement_documents,
            settlements=settlements,
            statement_invoice_refs=statement_invoice_refs,
            statement_payment_refs=statement_payment_refs,
            statements_missing_amounts=statements_missing_amounts,
        ),
        items=statement_items,
        documents=statement_documents,
    )

    component_stage_status = "missing"
    if component_documents and not missing_invoice_refs and not missing_credit_refs:
        component_stage_status = "ready"
    elif component_documents or missing_invoice_refs or missing_credit_refs:
        component_stage_status = "partial"

    component_items: list[str] = []
    if missing_invoice_refs:
        component_items.append(
            f"Missing imported invoice refs: {', '.join(missing_invoice_refs[:8])}"
        )
    if missing_credit_refs:
        component_items.append(
            f"Missing imported credit-note refs: {', '.join(missing_credit_refs[:8])}"
        )
    if settlements and not component_items:
        component_items.append(
            f"{len(settlements)} settlement group(s) already net invoice and credit-note lines against the bank payment"
        )
    elif component_documents:
        component_items.append(
            f"{len(component_documents)} invoice / credit document(s) are already connected to this supplier-period"
        )
    elif statement_invoice_refs or statement_credit_refs:
        component_items.append(
            "The statement references invoices or credits, but the imported document set is still incomplete"
        )

    component_stage = ReconciliationFlowStage(
        key="components",
        title="Invoices & Credit Notes",
        status=component_stage_status,
        summary=_build_component_stage_summary(
            component_documents=component_documents,
            missing_invoice_refs=missing_invoice_refs,
            missing_credit_refs=missing_credit_refs,
            settlements=settlements,
        ),
        items=component_items,
        documents=component_documents,
    )

    action_stage = ReconciliationFlowStage(
        key="resolve",
        title="Resolve",
        status=_action_stage_status(analysis.resolution_bucket),
        summary=analysis.resolution_reason or "Use the evidence chain above to resolve the row.",
        items=[
            item
            for item in [
                analysis.analysis_note,
                _next_step_for_flow(
                    transaction=transaction,
                    analysis=analysis,
                    settlements=settlements,
                    statement_documents=statement_documents,
                    missing_invoice_refs=missing_invoice_refs,
                    missing_credit_refs=missing_credit_refs,
                    statements_missing_amounts=statements_missing_amounts,
                ),
            ]
            if item
        ],
    )

    flow_type = "document_gap"
    if settlements or statement_documents:
        flow_type = "statement_first"
    elif analysis.exact_matches or analysis.suggested_matches:
        flow_type = "invoice_first"
    elif analysis.supporting_matches:
        flow_type = "support_only"
    elif analysis.resolution_bucket == "no_document_expected":
        flow_type = "no_document_expected"

    return ReconciliationFlow(
        flow_type=flow_type,
        supplier_label=supplier_label,
        bank_counterparty=bank_counterparty,
        next_step=_next_step_for_flow(
            transaction=transaction,
            analysis=analysis,
            settlements=settlements,
            statement_documents=statement_documents,
            missing_invoice_refs=missing_invoice_refs,
            missing_credit_refs=missing_credit_refs,
            statements_missing_amounts=statements_missing_amounts,
        ),
        stages=[supplier_stage, statement_stage, component_stage, action_stage],
        settlements=settlements,
    )


def build_transaction_reconciliation_item(
    *,
    transaction: Transaction,
    documents: list[Document],
    supporting_documents: list[Document] | None = None,
    document_ledgers: list[ParsedDocumentLedger] | None = None,
    supporting_document_ledgers: list[ParsedDocumentLedger] | None = None,
) -> ReconciliationTransactionItem:
    invoice_ledgers = document_ledgers if document_ledgers is not None else build_document_ledgers(documents)
    support_docs = supporting_documents or []
    support_ledgers = (
        supporting_document_ledgers
        if supporting_document_ledgers is not None
        else build_document_ledgers(support_docs)
    )
    item = ReconciliationTransactionItem(
        transaction_id=transaction.id,
        source_type=transaction.source_type,
        row_number=transaction.row_number,
        pub=transaction.pub,
        transaction_date=transaction.transaction_date,
        description1=transaction.description1,
        description2=transaction.description2,
        category=transaction.category,
        transaction_type=transaction.transaction_type,
        debit_amount=transaction.debit_amount,
        credit_amount=transaction.credit_amount,
        annotation_types=list(transaction.annotation_types or []),
        annotation_notes=list(transaction.annotation_notes or []),
        has_linked_annotation=transaction.has_linked_annotation,
    )

    exact_matches = _find_exact_matches(transaction=transaction, documents=documents)
    exact_amount_total = _sum_match_amounts(exact_matches)
    amount_balanced = _amounts_balance(transaction.debit_amount, exact_amount_total)

    if exact_matches:
        item.exact_matches = exact_matches
        if amount_balanced:
            item.status = "matched"
            _populate_resolution_guidance(
                item=item,
                transaction=transaction,
                invoice_documents=documents,
                supporting_documents=support_docs,
            )
            return item

        additional_suggestions = _find_completion_suggestions(
            transaction=transaction,
            documents=documents,
            document_ledgers=invoice_ledgers,
            exact_matches=exact_matches,
        )
        if additional_suggestions:
            item.status = "suggested"
            item.suggested_matches = additional_suggestions
            _populate_resolution_guidance(
                item=item,
                transaction=transaction,
                invoice_documents=documents,
                supporting_documents=support_docs,
            )
            return item

        item.status = "partial"
        _populate_resolution_guidance(
            item=item,
            transaction=transaction,
            invoice_documents=documents,
            supporting_documents=support_docs,
        )
        return item

    suggested_matches = _find_suggested_matches(
        transaction=transaction,
        documents=documents,
        document_ledgers=invoice_ledgers,
        supporting_document_ledgers=support_ledgers,
    )
    if suggested_matches:
        item.status = "suggested"
        item.suggested_matches = suggested_matches
        _populate_resolution_guidance(
            item=item,
            transaction=transaction,
            invoice_documents=documents,
            supporting_documents=support_docs,
        )
        return item

    support_matches = _find_supporting_document_suggestions(
        transaction=transaction,
        documents=support_docs,
        ledgers=support_ledgers,
        invoice_ledgers=invoice_ledgers,
    )
    if support_matches:
        item.supporting_matches = support_matches
        item.analysis_note = "Supporting supplier documents were found, but no invoice amount match was detected"
        support_payment_note = _build_support_payment_analysis(
            transaction=transaction,
            invoice_ledgers=invoice_ledgers,
            supporting_matches=support_matches,
            supporting_document_ledgers=support_ledgers,
        )
        if support_payment_note:
            item.status = "suggested"
            item.analysis_note = support_payment_note
            _populate_resolution_guidance(
                item=item,
                transaction=transaction,
                invoice_documents=documents,
                supporting_documents=support_docs,
            )
            return item

    item.status = "unmatched"
    _populate_resolution_guidance(
        item=item,
        transaction=transaction,
        invoice_documents=documents,
        supporting_documents=support_docs,
    )
    return item


def _populate_resolution_guidance(
    *,
    item: ReconciliationTransactionItem,
    transaction: Transaction,
    invoice_documents: list[Document],
    supporting_documents: list[Document],
) -> None:
    if item.status == "matched":
        item.resolution_bucket = "confirm_match"
        item.recommended_review_status = "linked"
        item.resolution_reason = "Exact document coverage is already present for the transaction amount"
        return

    if item.status == "partial":
        item.resolution_bucket = "complete_partial_match"
        item.recommended_review_status = None
        item.resolution_reason = (
            "Some exact document coverage exists, but the full transaction amount is not yet explained"
        )
        return

    if item.status == "suggested":
        if item.suggested_matches:
            item.resolution_bucket = "confirm_match"
            item.recommended_review_status = "linked"
            item.resolution_reason = "A supplier-aligned invoice suggestion is available for confirmation"
            return

        if item.supporting_matches:
            item.resolution_bucket = "review_supporting_docs"
            item.recommended_review_status = "supporting_docs_only"
            item.resolution_reason = (
                "Supporting supplier documents are available and likely explain the payment as a statement/account settlement"
            )
            return

    if item.supporting_matches:
        item.resolution_bucket = "review_supporting_docs"
        item.recommended_review_status = "supporting_docs_only"
        item.resolution_reason = "Supporting supplier documents are available for manual review"
        return

    if _looks_like_no_document_expected(transaction):
        item.resolution_bucket = "no_document_expected"
        item.recommended_review_status = "no_document_expected"
        item.resolution_reason = "The bank line looks like a bank/internal charge rather than a supplier invoice event"
        return

    if _looks_like_individual_payment(transaction):
        item.resolution_bucket = "awaiting_document"
        item.recommended_review_status = "awaiting_document"
        item.resolution_reason = (
            "The bank line looks like a transfer or reimbursement to an individual and needs supporting expense evidence"
        )
        return

    if _has_related_supplier_documents(
        transaction=transaction,
        invoice_documents=invoice_documents,
        supporting_documents=supporting_documents,
    ):
        item.resolution_bucket = "needs_matcher_improvement"
        item.recommended_review_status = None
        item.resolution_reason = (
            "Supplier-related documents exist nearby, but the current matcher did not produce a clean resolution"
        )
        return

    item.resolution_bucket = "awaiting_document"
    item.recommended_review_status = "awaiting_document"
    item.resolution_reason = "No matching supplier documents were found for the transaction yet"


async def sync_exact_transaction_document_links(
    *,
    db: AsyncSession,
    user_id,
    exact_matches_by_transaction: dict[uuid.UUID, list[ReconciliationDocumentMatch]],
) -> None:
    transaction_ids = list(exact_matches_by_transaction.keys())
    if not transaction_ids:
        return

    expected_pairs = {
        (transaction_id, match.document_id)
        for transaction_id, matches in exact_matches_by_transaction.items()
        for match in matches
    }

    existing_result = await db.execute(
        select(TransactionDocumentLink).where(
            TransactionDocumentLink.user_id == user_id,
            TransactionDocumentLink.transaction_id.in_(transaction_ids),
            TransactionDocumentLink.role == "invoice",
            TransactionDocumentLink.note == AUTO_EXACT_LINK_NOTE,
        )
    )
    existing_links = list(existing_result.scalars().all())
    existing_by_pair = {
        (link.transaction_id, link.document_id): link
        for link in existing_links
    }

    stale_link_ids = [
        link.id
        for link in existing_links
        if (link.transaction_id, link.document_id) not in expected_pairs
    ]
    if stale_link_ids:
        await db.execute(
            delete(TransactionDocumentLink).where(TransactionDocumentLink.id.in_(stale_link_ids))
        )

    for transaction_id, matches in exact_matches_by_transaction.items():
        for match in matches:
            pair = (transaction_id, match.document_id)
            link = existing_by_pair.get(pair)
            if link is None:
                db.add(
                    TransactionDocumentLink(
                        user_id=user_id,
                        transaction_id=transaction_id,
                        document_id=match.document_id,
                        role="invoice",
                        status="confirmed",
                        score=1.0,
                        confidence="high",
                        match_reason=match.reason,
                        amount_applied=match.amount,
                        note=AUTO_EXACT_LINK_NOTE,
                    )
                )
                continue

            link.status = "confirmed"
            link.score = 1.0
            link.confidence = "high"
            link.match_reason = match.reason
            link.amount_applied = match.amount
            link.note = AUTO_EXACT_LINK_NOTE

    await db.flush()


def _document_is_matchable(document: Document) -> bool:
    if document.extraction_status == "split":
        return False
    if "multiple_invoice_records" in (document.review_reasons or []):
        return False
    return document.amount is not None


def _find_exact_matches(
    *,
    transaction: Transaction,
    documents: list[Document],
) -> list[ReconciliationDocumentMatch]:
    notes_text = " ".join(transaction.annotation_notes or []).lower()
    if not notes_text:
        return []

    matches: list[ReconciliationDocumentMatch] = []
    seen_document_ids: set[uuid.UUID] = set()
    for document in documents:
        if not document.reference:
            continue
        reference = document.reference.lower().strip()
        pattern = rf"(?<![a-z0-9]){re.escape(reference)}(?![a-z0-9])"
        if not re.search(pattern, notes_text) or document.id in seen_document_ids:
            continue
        seen_document_ids.add(document.id)
        matches.append(
            ReconciliationDocumentMatch(
                document_id=document.id,
                document_type=document.document_type,
                supplier=document.supplier,
                reference=document.reference,
                document_date=document.document_date,
                amount=document.amount,
                vat_amount=document.vat_amount,
                score=1.0,
                reason=EXACT_REFERENCE_REASON,
            )
        )

    matches.sort(
        key=lambda match: (
            match.document_date or date.min,
            match.reference or "",
        )
    )
    return matches


def _find_completion_suggestions(
    *,
    transaction: Transaction,
    documents: list[Document],
    document_ledgers: list[ParsedDocumentLedger],
    exact_matches: list[ReconciliationDocumentMatch],
) -> list[ReconciliationDocumentMatch]:
    if transaction.debit_amount is None:
        return []

    exact_total = _sum_match_amounts(exact_matches)
    if exact_total is None or exact_total >= transaction.debit_amount:
        return []

    remaining_amount = transaction.debit_amount - exact_total
    excluded_document_ids = {match.document_id for match in exact_matches}
    anchored_supplier = exact_matches[0].supplier if len({match.supplier for match in exact_matches}) == 1 else None

    return _find_grouped_suggestion(
        transaction=transaction,
        documents=documents,
        document_ledgers=document_ledgers,
        target_amount=remaining_amount,
        excluded_document_ids=excluded_document_ids,
        anchored_supplier=anchored_supplier,
        reason_prefix="Remaining amount after exact reference note matches",
    )


def _find_suggested_matches(
    *,
    transaction: Transaction,
    documents: list[Document],
    document_ledgers: list[ParsedDocumentLedger],
    supporting_document_ledgers: list[ParsedDocumentLedger] | None = None,
) -> list[ReconciliationDocumentMatch]:
    single_matches = _find_single_document_suggestions(
        transaction=transaction,
        documents=documents,
        document_ledgers=document_ledgers,
        supporting_document_ledgers=supporting_document_ledgers or [],
    )
    if single_matches:
        return single_matches

    if transaction.debit_amount is None:
        return []

    grouped_matches = _find_grouped_suggestion(
        transaction=transaction,
        documents=documents,
        document_ledgers=document_ledgers,
        target_amount=transaction.debit_amount,
        excluded_document_ids=set(),
        anchored_supplier=None,
        reason_prefix="Invoice combination total matches the transaction amount",
    )
    return grouped_matches


def _find_single_document_suggestions(
    *,
    transaction: Transaction,
    documents: list[Document],
    document_ledgers: list[ParsedDocumentLedger],
    supporting_document_ledgers: list[ParsedDocumentLedger],
) -> list[ReconciliationDocumentMatch]:
    if transaction.debit_amount is None or transaction.transaction_date is None:
        return []

    transaction_tokens = _build_transaction_tokens(transaction)
    generic_annotation_only = _has_generic_annotations_only(transaction)
    suggestions: list[ReconciliationDocumentMatch] = []
    document_by_id = {document.id: document for document in documents}
    statement_invoice_context = _build_statement_invoice_context(
        transaction=transaction,
        supporting_document_ledgers=supporting_document_ledgers,
    )

    for ledger in document_ledgers:
        document_entry = _primary_invoice_entry(ledger)
        if document_entry is None or document_entry.amount != transaction.debit_amount:
            continue
        document = document_by_id.get(ledger.document_id)
        if document is None:
            continue
        document_date = document_entry.event_date
        if document_date is None:
            continue
        date_difference = abs((transaction.transaction_date - document_date).days)
        if date_difference > 60:
            continue

        pub_matches, pub_conflict, pub_reason = _pub_compatibility(
            transaction=transaction,
            document=document,
        )
        if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and pub_conflict:
            continue

        document_tokens = _build_document_tokens(document)
        overlap = transaction_tokens & document_tokens
        supplier_matches, supplier_reason = _supplier_compatibility(
            transaction=transaction,
            document=document,
            overlap=overlap,
        )
        if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and not supplier_matches:
            continue

        score = Decimal("0.45")
        score += Decimal(str(_date_score(date_difference)))
        score += Decimal(str(_token_overlap_score(overlap)))
        if supplier_matches and transaction.source_type == BANK_STATEMENT_SOURCE_TYPE:
            score += Decimal("0.15")
        if pub_matches and transaction.source_type == BANK_STATEMENT_SOURCE_TYPE:
            score += Decimal("0.12")
        if not generic_annotation_only and overlap:
            score += Decimal("0.05")

        statement_context = (
            statement_invoice_context.get(document_entry.reference)
            if document_entry.reference
            else None
        )
        if statement_context is not None:
            score += Decimal("0.12")
            if statement_context["due_date_difference"] == 0:
                score += Decimal("0.08")
            elif statement_context["due_date_difference"] is not None and statement_context["due_date_difference"] <= 3:
                score += Decimal("0.05")
            elif statement_context["due_date_difference"] is not None and statement_context["due_date_difference"] <= 7:
                score += Decimal("0.03")

        if float(score) < 0.55:
            continue

        reason_parts = ["Amount matches exactly"]
        reason_parts.append(f"Invoice date is {date_difference} day(s) from the bank transaction")
        if overlap:
            reason_parts.append("Supplier or file metadata overlaps with transaction text")
        elif supplier_reason:
            reason_parts.append(supplier_reason)
        if pub_reason:
            reason_parts.append(pub_reason)
        if statement_context is not None:
            reason_parts.append("Supporting statement references this invoice")
            if statement_context["due_date_difference"] == 0:
                reason_parts.append("Statement due date matches the bank transaction date")
            elif statement_context["due_date_difference"] is not None:
                reason_parts.append(
                    f"Statement due date is {statement_context['due_date_difference']} day(s) from the bank transaction"
                )

        suggestions.append(
            ReconciliationDocumentMatch(
                document_id=ledger.document_id,
                document_type=ledger.document_type,
                supplier=ledger.supplier,
                reference=document_entry.reference,
                document_date=document_date,
                amount=document_entry.amount,
                vat_amount=document_entry.vat_amount,
                score=round(float(score), 2),
                reason="; ".join(reason_parts),
            )
        )

    suggestions.sort(
        key=lambda match: (
            match.score or 0,
            match.document_date or date.min,
            match.reference or "",
        ),
        reverse=True,
    )
    return suggestions[:3]


def _build_statement_invoice_context(
    *,
    transaction: Transaction,
    supporting_document_ledgers: list[ParsedDocumentLedger],
) -> dict[str, dict[str, int | None]]:
    context: dict[str, dict[str, int | None]] = {}
    if transaction.transaction_date is None:
        return context

    for ledger in supporting_document_ledgers:
        if not ledger.is_financial:
            continue
        for entry in ledger.entries:
            if entry.entry_kind != LEDGER_ENTRY_INVOICE or not entry.reference:
                continue
            due_date_difference = (
                abs((transaction.transaction_date - entry.due_date).days)
                if entry.due_date is not None
                else None
            )
            event_date_difference = (
                abs((transaction.transaction_date - entry.event_date).days)
                if entry.event_date is not None
                else None
            )
            current = context.get(entry.reference)
            candidate = {
                "due_date_difference": due_date_difference,
                "event_date_difference": event_date_difference,
            }
            if current is None:
                context[entry.reference] = candidate
                continue

            current_due = current["due_date_difference"]
            candidate_due = candidate["due_date_difference"]
            if candidate_due is not None and (current_due is None or candidate_due < current_due):
                context[entry.reference] = candidate
                continue
            if candidate_due == current_due:
                current_event = current["event_date_difference"]
                candidate_event = candidate["event_date_difference"]
                if candidate_event is not None and (current_event is None or candidate_event < current_event):
                    context[entry.reference] = candidate

    return context


def _support_document_timing_context(
    *,
    transaction_date: date,
    document: Document,
    ledger: ParsedDocumentLedger | None,
) -> dict[str, object]:
    period_start = ledger.period_start if ledger is not None else None
    period_end = ledger.period_end if ledger is not None else None

    if period_start is not None or period_end is not None:
        effective_start = period_start or period_end
        effective_end = period_end or period_start
        if effective_start and effective_end and effective_start > effective_end:
            effective_start, effective_end = effective_end, effective_start

        if effective_start is not None and effective_end is not None:
            if effective_start <= transaction_date <= effective_end:
                return {
                    "skip": False,
                    "score": 0.2,
                    "reason": (
                        f"Statement period {effective_start.isoformat()} to {effective_end.isoformat()} "
                        "covers the bank transaction date"
                    ),
                }

            gap_days = min(
                abs((transaction_date - effective_start).days),
                abs((transaction_date - effective_end).days),
            )
            if gap_days > 45:
                return {
                    "skip": True,
                    "score": 0.0,
                    "reason": "Statement period is too far from the bank transaction date",
                }

            return {
                "skip": False,
                "score": _date_score(gap_days) + 0.04,
                "reason": (
                    f"Statement period {effective_start.isoformat()} to {effective_end.isoformat()} "
                    f"is {gap_days} day(s) from the bank transaction"
                ),
            }

    if document.document_date is None:
        return {
            "skip": True,
            "score": 0.0,
            "reason": "Supporting document has no usable statement period or document date",
        }

    date_difference = abs((transaction_date - document.document_date).days)
    if date_difference > 45:
        return {
            "skip": True,
            "score": 0.0,
            "reason": "Supporting document date is too far from the bank transaction",
        }

    return {
        "skip": False,
        "score": _date_score(date_difference),
        "reason": (
            f"{document.document_type.replace('_', ' ').title()} date is {date_difference} day(s) "
            "from the bank transaction"
        ),
    }


def _statement_imported_invoice_overlap(
    *,
    transaction: Transaction,
    statement_ledger: ParsedDocumentLedger,
    invoice_ledgers: list[ParsedDocumentLedger],
) -> list[str]:
    supplier_keys = _build_ledger_supplier_keys(statement_ledger)
    statement_refs = {
        entry.reference
        for entry in statement_ledger.entries
        if entry.entry_kind == LEDGER_ENTRY_INVOICE and entry.reference
    }
    if not statement_refs:
        return []

    overlapping_refs: list[str] = []
    for ledger in invoice_ledgers:
        if supplier_keys and not _supplier_keys_overlap(supplier_keys, _build_ledger_supplier_keys(ledger)):
            continue
        entry = _primary_invoice_entry(ledger)
        if entry is None or not entry.reference:
            continue
        if entry.reference not in statement_refs:
            continue
        if entry.event_date is not None and transaction.transaction_date is not None:
            if abs((transaction.transaction_date - entry.event_date).days) > 75:
                continue
        overlapping_refs.append(entry.reference)

    return _ordered_unique(overlapping_refs)


def _find_grouped_suggestion(
    *,
    transaction: Transaction,
    documents: list[Document],
    document_ledgers: list[ParsedDocumentLedger],
    target_amount: Decimal,
    excluded_document_ids: set[uuid.UUID],
    anchored_supplier: str | None,
    reason_prefix: str,
) -> list[ReconciliationDocumentMatch]:
    if transaction.transaction_date is None or target_amount <= 0:
        return []

    transaction_tokens = _build_transaction_tokens(transaction)
    transaction_supplier_keys = _build_transaction_supplier_keys(transaction)
    candidates_by_supplier: dict[str, list[ParsedLedgerEntry]] = defaultdict(list)
    pub_match_by_document_id: dict[uuid.UUID, bool] = {}
    document_by_id = {document.id: document for document in documents}

    for ledger in document_ledgers:
        document = document_by_id.get(ledger.document_id)
        document_entry = _primary_invoice_entry(ledger)
        if document is None or document_entry is None:
            continue
        if ledger.document_id in excluded_document_ids:
            continue
        if document_entry.amount is None or document_entry.amount <= 0 or document_entry.amount > target_amount:
            continue
        if document_entry.event_date is None:
            continue
        date_difference = abs((transaction.transaction_date - document_entry.event_date).days)
        if date_difference > 60:
            continue
        if anchored_supplier and ledger.supplier != anchored_supplier:
            continue
        pub_matches, pub_conflict, _ = _pub_compatibility(
            transaction=transaction,
            document=document,
        )
        if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and pub_conflict:
            continue
        if (
            transaction.source_type == BANK_STATEMENT_SOURCE_TYPE
            and not _supplier_keys_overlap(transaction_supplier_keys, _build_document_supplier_keys(document))
        ):
            continue
        candidates_by_supplier[ledger.supplier].append(document_entry)
        pub_match_by_document_id[ledger.document_id] = pub_matches

    best_combo: tuple[list[ParsedLedgerEntry], float, str] | None = None
    for supplier, supplier_entries in candidates_by_supplier.items():
        supplier_entries.sort(
            key=lambda entry: (
                abs((transaction.transaction_date - entry.event_date).days) if entry.event_date else 999,
                entry.amount or Decimal("0"),
            )
        )
        candidate_pool = supplier_entries[:8]
        for combo_size in range(2, min(len(candidate_pool), 4) + 1):
            for combo in combinations(candidate_pool, combo_size):
                combo_total = sum((entry.amount or Decimal("0")) for entry in combo)
                if combo_total != target_amount:
                    continue

                combo_date_difference = max(
                    abs((transaction.transaction_date - entry.event_date).days)
                    for entry in combo
                    if entry.event_date is not None
                )
                combo_tokens = set()
                for entry in combo:
                    combo_tokens.update(_build_document_tokens(document_by_id[entry.document_id]))

                overlap = transaction_tokens & combo_tokens
                score = 0.52 + _date_score(combo_date_difference) + _token_overlap_score(overlap)
                if supplier == anchored_supplier:
                    score += 0.1
                if (
                    transaction.source_type == BANK_STATEMENT_SOURCE_TYPE
                    and _supplier_keys_overlap(
                        transaction_supplier_keys,
                        _build_document_supplier_keys(document_by_id[combo[0].document_id]),
                    )
                ):
                    score += 0.15
                if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and any(
                    pub_match_by_document_id.get(entry.document_id, False) for entry in combo
                ):
                    score += 0.12
                score += min(0.05 * (combo_size - 1), 0.15)

                reason = (
                    f"{reason_prefix}; {combo_size} invoice documents from {supplier} "
                    f"sum exactly to {target_amount}"
                )
                if overlap:
                    reason += "; supplier or file metadata overlaps with transaction text"
                elif transaction.source_type == BANK_STATEMENT_SOURCE_TYPE:
                    reason += "; bank payee aligns with the supplier"
                if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and any(
                    pub_match_by_document_id.get(entry.document_id, False) for entry in combo
                ):
                    reason += "; document venue aligns with the transaction pub"

                if best_combo is None or score > best_combo[1]:
                    best_combo = (list(combo), score, reason)

    if best_combo is None:
        return []

    combo_entries, score, reason = best_combo
    return [
        ReconciliationDocumentMatch(
            document_id=entry.document_id,
            document_type=document_by_id[entry.document_id].document_type,
            supplier=document_by_id[entry.document_id].supplier,
            reference=entry.reference,
            document_date=entry.event_date,
            amount=entry.amount,
            vat_amount=entry.vat_amount,
            score=round(score, 2),
            reason=reason,
        )
        for entry in sorted(
            combo_entries,
            key=lambda entry: (
                entry.event_date or date.min,
                entry.reference or "",
            ),
        )
    ]


def _build_transaction_tokens(transaction: Transaction) -> set[str]:
    description1 = transaction.description1
    if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE:
        description1 = _clean_bank_statement_counterparty(description1) or description1

    return _tokenize(
        " ".join(
            part
            for part in (
                description1,
                transaction.description2,
                transaction.category,
                transaction.expected_supplier,
                " ".join(transaction.annotation_notes or []),
            )
            if part
        )
    )


def _build_document_tokens(document: Document) -> set[str]:
    return _tokenize(
        " ".join(
            part
            for part in (
                document.supplier,
                document.reference,
                document.source_email_subject,
                document.source_email_sender,
                document.attachment_name,
            )
            if part
        )
    )


def _find_supporting_document_suggestions(
    *,
    transaction: Transaction,
    documents: list[Document],
    ledgers: list[ParsedDocumentLedger],
    invoice_ledgers: list[ParsedDocumentLedger],
) -> list[ReconciliationDocumentMatch]:
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE or transaction.transaction_date is None:
        return []

    transaction_tokens = _build_transaction_tokens(transaction)
    suggestions: list[ReconciliationDocumentMatch] = []
    ledger_by_document_id = {ledger.document_id: ledger for ledger in ledgers}
    settlements_by_document_id = {
        ledger.document_id: build_statement_settlements(ledger)
        for ledger in ledgers
    }

    for document in documents:
        pub_matches, pub_conflict, pub_reason = _pub_compatibility(
            transaction=transaction,
            document=document,
        )
        if pub_conflict:
            continue

        document_tokens = _build_document_tokens(document)
        overlap = transaction_tokens & document_tokens
        supplier_matches, supplier_reason = _supplier_compatibility(
            transaction=transaction,
            document=document,
            overlap=overlap,
        )
        if not supplier_matches:
            continue

        ledger = ledger_by_document_id.get(document.id)
        timing_context = _support_document_timing_context(
            transaction_date=transaction.transaction_date,
            document=document,
            ledger=ledger,
        )
        if timing_context["skip"]:
            continue
        score = Decimal("0.3")
        score += Decimal(str(timing_context["score"]))
        score += Decimal(str(_token_overlap_score(overlap)))
        if pub_matches:
            score += Decimal("0.12")
        reason_parts = [supplier_reason or "Supporting document aligns with the bank payee"]
        reason_parts.append(timing_context["reason"])
        if pub_reason:
            reason_parts.append(pub_reason)
        if document.amount is not None and transaction.debit_amount is not None:
            amount_delta = abs(transaction.debit_amount - document.amount)
            if amount_delta == 0:
                score += Decimal("0.1")
                reason_parts.append("Support document amount matches exactly")
            elif amount_delta <= Decimal("5.00"):
                score += Decimal("0.05")
                reason_parts.append(f"Support document amount is within {amount_delta} of the bank debit")
        if ledger is not None:
            if ledger.is_financial:
                exact_statement_lines = find_matching_ledger_entries(
                    entries=ledger.entries,
                    amount=transaction.debit_amount,
                    entry_kinds={LEDGER_ENTRY_PAYMENT, LEDGER_ENTRY_INVOICE, LEDGER_ENTRY_CREDIT_NOTE},
                )
                matching_settlements = [
                    settlement
                    for settlement in settlements_by_document_id.get(document.id, [])
                    if settlement.payment_entry.amount == transaction.debit_amount
                ]
                if ledger.statement_kind == "supplier_statement":
                    score += Decimal("0.08")
                    reason_parts.append("Statement includes supplier account settlement lines")
                elif ledger.statement_kind == "trade_statement":
                    score += Decimal("0.08")
                    reason_parts.append("Statement includes trade-account invoice and receipt lines")
                elif ledger.statement_kind == "sub_account_statement":
                    score += Decimal("0.04")
                    reason_parts.append("Statement tracks sub-account discount balances")
                invoice_refs = _ledger_invoice_references(ledger)
                payment_refs = _ledger_payment_references(ledger)
                if invoice_refs:
                    score += Decimal("0.05")
                    reason_parts.append(
                        f"Statement references {len(invoice_refs)} invoice line(s)"
                    )
                    imported_ref_overlap = _statement_imported_invoice_overlap(
                        transaction=transaction,
                        statement_ledger=ledger,
                        invoice_ledgers=invoice_ledgers,
                    )
                    if imported_ref_overlap:
                        score += Decimal("0.08")
                        reason_parts.append(
                            f"Statement references {len(imported_ref_overlap)} imported invoice(s) from the review window"
                        )
                if payment_refs:
                    score += Decimal("0.03")
                    reason_parts.append(
                        f"Statement references {len(payment_refs)} payment line(s)"
                    )
                if matching_settlements:
                    score += Decimal("0.14")
                    reason_parts.append(
                        f"Statement settlement math resolves the bank amount via {_describe_settlement_components(matching_settlements[0])}"
                    )
                elif exact_statement_lines:
                    score += Decimal("0.1")
                    reason_parts.append(
                        f"Statement contains {len(exact_statement_lines)} line(s) at the bank amount"
                    )
                    line_refs = [entry.reference for entry in exact_statement_lines if entry.reference]
                    if line_refs:
                        reason_parts.append(
                            f"Matching statement refs include {', '.join(line_refs[:6])}"
                        )
                else:
                    fuzzy_hits = _find_fuzzy_statement_amount_contexts(
                        ledger=ledger,
                        amount=transaction.debit_amount,
                    )
                    if fuzzy_hits:
                        score += Decimal("0.06")
                        reason_parts.append(
                            f"Statement OCR includes the bank amount near {' / '.join(sorted(fuzzy_hits[0].keywords))} context"
                        )
            else:
                score -= Decimal("0.04")
                reason_parts.append("Marked as non-financial support only")

        suggestions.append(
            ReconciliationDocumentMatch(
                document_id=document.id,
                document_type=document.document_type,
                supplier=document.supplier,
                reference=document.reference,
                document_date=document.document_date,
                amount=document.amount,
                vat_amount=document.vat_amount,
                score=round(float(score), 2),
                reason="; ".join(reason_parts),
            )
        )

    suggestions.sort(
        key=lambda match: (
            match.score or 0,
            match.document_date or date.min,
            match.document_type,
            match.reference or "",
        ),
        reverse=True,
    )
    return suggestions[:3]


def _build_support_payment_analysis(
    *,
    transaction: Transaction,
    invoice_ledgers: list[ParsedDocumentLedger],
    supporting_matches: list[ReconciliationDocumentMatch],
    supporting_document_ledgers: list[ParsedDocumentLedger],
) -> str | None:
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE or transaction.transaction_date is None:
        return None
    if not supporting_matches:
        return None

    primary_supplier = supporting_matches[0].supplier
    primary_supplier_keys = build_supplier_lookup_keys(primary_supplier)
    strong_support_matches = [
        match
        for match in supporting_matches
        if match.supplier == primary_supplier
        and match.document_type in {"statement", "credit_note"}
        and (match.score or 0.0) >= 0.45
    ]

    nearby_supplier_invoice_entries = [
        entry
        for ledger in invoice_ledgers
        if ledger.is_financial
        and _supplier_keys_overlap(primary_supplier_keys, _build_ledger_supplier_keys(ledger))
        for entry in ledger.entries
        if entry.entry_kind == LEDGER_ENTRY_INVOICE
        and entry.event_date is not None
        and abs((transaction.transaction_date - entry.event_date).days) <= 45
    ]

    matched_support_ledgers = [
        ledger
        for ledger in supporting_document_ledgers
        if ledger.document_id in {match.document_id for match in supporting_matches}
        and ledger.supplier == primary_supplier
    ]
    financial_support_ledgers = [ledger for ledger in matched_support_ledgers if ledger.is_financial]
    non_financial_support_ledgers = [ledger for ledger in matched_support_ledgers if not ledger.is_financial]
    matching_settlements = [
        settlement
        for ledger in financial_support_ledgers
        for settlement in build_statement_settlements(ledger)
        if settlement.payment_entry.amount == transaction.debit_amount
    ]
    nearby_invoice_references = {entry.reference for entry in nearby_supplier_invoice_entries if entry.reference}
    statement_invoice_refs = sorted(
        {
            entry.reference
            for ledger in financial_support_ledgers
            for entry in ledger.entries
            if entry.entry_kind == LEDGER_ENTRY_INVOICE and entry.reference
        }
    )
    statement_payment_refs = sorted(
        {
            entry.reference
            for ledger in financial_support_ledgers
            for entry in ledger.entries
            if entry.entry_kind == LEDGER_ENTRY_PAYMENT and entry.reference
        }
    )
    overlapping_statement_invoice_refs = [
        reference for reference in statement_invoice_refs if reference in nearby_invoice_references
    ]
    matched_statement_lines = [
        entry
        for ledger in financial_support_ledgers
        for entry in find_matching_ledger_entries(
            entries=ledger.entries,
            amount=transaction.debit_amount,
            entry_kinds={LEDGER_ENTRY_PAYMENT, LEDGER_ENTRY_INVOICE, LEDGER_ENTRY_CREDIT_NOTE},
        )
    ]
    has_supplier_statement = any(ledger.statement_kind == "supplier_statement" for ledger in financial_support_ledgers)
    has_trade_statement = any(ledger.statement_kind == "trade_statement" for ledger in financial_support_ledgers)
    has_sub_account_statement = any(
        ledger.statement_kind == "sub_account_statement" for ledger in financial_support_ledgers
    )
    if matching_settlements:
        settlement = matching_settlements[0]
        note_parts = [
            f"Supplier statement settlement matches the bank amount {transaction.debit_amount}",
            f"payment ref {settlement.payment_entry.reference or '—'} clears {_describe_settlement_components(settlement)}",
        ]
        if overlapping_statement_invoice_refs:
            note_parts.append(
                f"the statement overlaps with {len(overlapping_statement_invoice_refs)} nearby imported invoice reference(s)"
            )
        elif statement_invoice_refs:
            note_parts.append(
                f"the statement references invoice refs {', '.join(statement_invoice_refs[:6])}"
            )
        if has_sub_account_statement:
            note_parts.append("discount/sub-account support is also present")
        if non_financial_support_ledgers:
            note_parts.append("non-financial operational documents were kept as context only")
        return "; ".join(note_parts)

    if matched_statement_lines:
        line_refs = [entry.reference for entry in matched_statement_lines if entry.reference]
        line_types = sorted({_ledger_entry_label(entry.entry_kind) for entry in matched_statement_lines})
        note_parts = [
            (
                f"Supplier statement contains {len(matched_statement_lines)} parsed {'/'.join(line_types) if line_types else 'statement'} line(s) "
                f"matching the bank amount {transaction.debit_amount}"
            )
        ]
        if line_refs:
            note_parts.append(f"matching refs include {', '.join(line_refs[:6])}")
        if overlapping_statement_invoice_refs:
            note_parts.append(
                f"the statement also references {len(overlapping_statement_invoice_refs)} nearby invoice line(s)"
            )
        elif financial_support_ledgers and statement_invoice_refs:
            note_parts.append(
                f"the statement references invoice refs {', '.join(statement_invoice_refs[:6])}, but the invoice PDFs are not imported yet"
            )
        if has_sub_account_statement:
            note_parts.append("discount/sub-account support is also present")
        if non_financial_support_ledgers:
            note_parts.append("non-financial operational documents were kept as context only")
        note_parts.append("likely direct-debit statement settlement rather than a standalone invoice match")
        return "; ".join(note_parts)

    fuzzy_support_hits = [
        (ledger, hit)
        for ledger in financial_support_ledgers
        for hit in _find_fuzzy_statement_amount_contexts(ledger=ledger, amount=transaction.debit_amount)
    ]
    if fuzzy_support_hits:
        ledger, hit = fuzzy_support_hits[0]
        note_parts = [
            f"Supplier statement OCR includes the bank amount {transaction.debit_amount}",
            f"near {' / '.join(sorted(hit.keywords))} context",
        ]
        if hit.reference:
            note_parts.append(f"near ref {hit.reference}")
        if statement_invoice_refs:
            note_parts.append(
                f"the statement also references invoice refs {', '.join(statement_invoice_refs[:6])}"
            )
        if non_financial_support_ledgers:
            note_parts.append("non-financial operational documents were kept as context only")
        note_parts.append(
            "structured line recovery is incomplete, but the statement likely explains the payment"
        )
        return "; ".join(note_parts)

    if len(nearby_supplier_invoice_entries) < 2:
        return None

    if has_supplier_statement and overlapping_statement_invoice_refs:
        note_parts = [
            (
                f"Supplier payment aligns with {len(financial_support_ledgers)} financial statement document(s) "
                f"covering {len(overlapping_statement_invoice_refs)} nearby invoice reference(s)"
            )
        ]
        if statement_payment_refs:
            note_parts.append(
                f"{len(statement_payment_refs)} payment/settlement line(s) are present on the statement"
            )
        if has_sub_account_statement:
            note_parts.append("sub-account discount support is also present")
        if non_financial_support_ledgers:
            note_parts.append("non-financial operational documents were kept as context only")
        note_parts.append("likely account/statement settlement rather than a single-invoice payment")
        return "; ".join(note_parts)

    if len(strong_support_matches) < 2:
        return None

    support_doc_types = sorted({match.document_type.replace("_", " ") for match in strong_support_matches})
    support_doc_label = ", ".join(support_doc_types)
    return (
        f"Supplier payment aligns with {len(strong_support_matches)} supporting {support_doc_label} document(s) "
        f"and {len(nearby_supplier_invoice_entries)} nearby {primary_supplier} invoice(s); "
        "likely account/statement settlement rather than a single-invoice payment"
    )


def _derive_flow_supplier_label(
    *,
    transaction: Transaction,
    analysis: ReconciliationTransactionItem,
    bank_counterparty: str | None,
) -> str | None:
    if transaction.expected_supplier:
        return transaction.expected_supplier
    for match in [*analysis.exact_matches, *analysis.suggested_matches, *analysis.supporting_matches]:
        if match.supplier:
            return match.supplier
    return bank_counterparty


def _collect_related_statement_ledgers(
    *,
    transaction: Transaction,
    analysis: ReconciliationTransactionItem,
    supporting_documents: list[Document],
    supporting_ledgers: list[ParsedDocumentLedger],
    persisted_links: list[TransactionDocumentLink],
    invoice_ledgers: list[ParsedDocumentLedger],
) -> list[ParsedDocumentLedger]:
    ledger_by_id = {ledger.document_id: ledger for ledger in supporting_ledgers}
    support_doc_by_id = {document.id: document for document in supporting_documents}
    selected_ids: list[uuid.UUID] = []

    for match in analysis.supporting_matches:
        document = support_doc_by_id.get(match.document_id)
        if document is not None and document.document_type == "statement" and match.document_id in ledger_by_id:
            selected_ids.append(match.document_id)

    for link in persisted_links:
        document = link.document
        if document is None or document.document_type != "statement":
            continue
        if link.document_id in ledger_by_id:
            selected_ids.append(link.document_id)

    if not selected_ids:
        transaction_supplier_keys = _build_transaction_supplier_keys(transaction)
        for document in supporting_documents:
            if document.document_type != "statement":
                continue
            pub_matches, pub_conflict, _ = _pub_compatibility(
                transaction=transaction,
                document=document,
            )
            if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and pub_conflict:
                continue
            if transaction_supplier_keys and not _supplier_keys_overlap(
                transaction_supplier_keys,
                _build_document_supplier_keys(document),
            ):
                continue
            if not pub_matches and transaction.pub:
                continue
            ledger = ledger_by_id.get(document.id)
            if transaction.transaction_date is not None:
                timing_context = _support_document_timing_context(
                    transaction_date=transaction.transaction_date,
                    document=document,
                    ledger=ledger,
                )
                if timing_context["skip"]:
                    continue
            selected_ids.append(document.id)

    ordered_ids = _ordered_unique(selected_ids)
    ledgers = [ledger_by_id[document_id] for document_id in ordered_ids if document_id in ledger_by_id]
    return [
        ledger
        for ledger in ledgers
        if _statement_is_flow_relevant(
            transaction=transaction,
            analysis=analysis,
            ledger=ledger,
            invoice_ledgers=invoice_ledgers,
        )
    ]


def _statement_is_flow_relevant(
    *,
    transaction: Transaction,
    analysis: ReconciliationTransactionItem,
    ledger: ParsedDocumentLedger,
    invoice_ledgers: list[ParsedDocumentLedger],
) -> bool:
    if not ledger.is_financial:
        return True

    matching_settlements = [
        settlement
        for settlement in build_statement_settlements(ledger)
        if transaction.debit_amount is not None and settlement.payment_entry.amount == transaction.debit_amount
    ]
    if matching_settlements:
        return True

    if analysis.resolution_bucket != "confirm_match":
        return True

    candidate_refs = {
        match.reference
        for match in [*analysis.exact_matches, *analysis.suggested_matches]
        if match.reference
    }
    statement_refs = {
        entry.reference
        for entry in ledger.entries
        if entry.entry_kind == LEDGER_ENTRY_INVOICE and entry.reference
    }
    if candidate_refs and statement_refs & candidate_refs:
        return True

    imported_overlap = _statement_imported_invoice_overlap(
        transaction=transaction,
        statement_ledger=ledger,
        invoice_ledgers=invoice_ledgers,
    )
    return bool(imported_overlap)


def _build_flow_component_documents(
    *,
    transaction: Transaction,
    analysis: ReconciliationTransactionItem,
    invoice_documents: list[Document],
    invoice_doc_by_id: dict[uuid.UUID, Document],
    invoice_ledger_by_id: dict[uuid.UUID, ParsedDocumentLedger],
    supporting_documents: list[Document],
    supporting_ledgers: list[ParsedDocumentLedger],
    statement_invoice_refs: list[str],
    statement_credit_refs: list[str],
) -> list[ReconciliationFlowDocument]:
    component_documents: list[ReconciliationFlowDocument] = []
    seen_document_ids: set[uuid.UUID] = set()

    for match in [*analysis.exact_matches, *analysis.suggested_matches]:
        component_documents.append(
            ReconciliationFlowDocument(
                document_id=match.document_id,
                supplier=match.supplier,
                document_type=match.document_type,
                reference=match.reference,
                document_date=match.document_date,
                amount=match.amount,
                vat_amount=match.vat_amount,
                score=match.score,
                role="invoice_candidate",
                reason=match.reason,
            )
        )
        seen_document_ids.add(match.document_id)

    transaction_supplier_keys = _build_transaction_supplier_keys(transaction)
    statement_context = _build_statement_invoice_context(
        transaction=transaction,
        supporting_document_ledgers=supporting_ledgers,
    )

    for reference in statement_invoice_refs:
        matched_documents = [
            document
            for document in invoice_documents
            if document.reference == reference
            and (
                not transaction_supplier_keys
                or _supplier_keys_overlap(
                    transaction_supplier_keys,
                    _build_document_supplier_keys(document),
                )
            )
        ]
        matched_documents.sort(
            key=lambda document: (
                _statement_reference_rank(
                    reference=reference,
                    document_date=document.document_date,
                    context=statement_context.get(reference),
                    transaction_date=transaction.transaction_date,
                ),
                document.document_date or date.max,
            )
        )
        for document in matched_documents[:2]:
            if document.id in seen_document_ids:
                continue
            pub_matches, pub_conflict, _ = _pub_compatibility(
                transaction=transaction,
                document=document,
            )
            if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and pub_conflict:
                continue
            ledger = invoice_ledger_by_id.get(document.id)
            entry = _primary_invoice_entry(ledger) if ledger else None
            component_documents.append(
                ReconciliationFlowDocument(
                    document_id=document.id,
                    supplier=document.supplier,
                    document_type=document.document_type,
                    reference=document.reference,
                    document_date=document.document_date,
                    amount=document.amount,
                    vat_amount=document.vat_amount,
                    score=0.88 if pub_matches else 0.82,
                    role="statement_reference",
                    reason=_statement_reference_reason(
                        reference=reference,
                        context=statement_context.get(reference),
                        transaction_date=transaction.transaction_date,
                    ),
                )
            )
            seen_document_ids.add(document.id)
            if entry is not None:
                break

    support_doc_by_id = {document.id: document for document in supporting_documents}
    for ledger in supporting_ledgers:
        document = support_doc_by_id.get(ledger.document_id)
        if document is None or document.document_type != "credit_note":
            continue
        if document.reference not in statement_credit_refs or document.id in seen_document_ids:
            continue
        pub_matches, pub_conflict, _ = _pub_compatibility(
            transaction=transaction,
            document=document,
        )
        if transaction.source_type == BANK_STATEMENT_SOURCE_TYPE and pub_conflict:
            continue
        component_documents.append(
            ReconciliationFlowDocument(
                document_id=document.id,
                supplier=document.supplier,
                document_type=document.document_type,
                reference=document.reference,
                document_date=document.document_date,
                amount=document.amount,
                vat_amount=document.vat_amount,
                score=0.8 if pub_matches else 0.74,
                role="statement_credit_reference",
                reason="Referenced by the supplier statement as a credit-note component",
            )
        )
        seen_document_ids.add(document.id)

    component_documents.sort(
        key=lambda document: (
            _flow_role_rank(document.role),
            -(document.score or 0.0),
            document.document_date or date.max,
            document.reference or "",
        )
    )
    return component_documents[:8]


def _statement_reference_rank(
    *,
    reference: str,
    document_date: date | None,
    context: dict[str, int | None] | None,
    transaction_date: date | None,
) -> tuple[int, int, int]:
    if context is None:
        return (1, 999, 999)
    due_difference = context.get("due_date_difference")
    event_difference = context.get("event_date_difference")
    doc_difference = (
        abs((transaction_date - document_date).days)
        if transaction_date is not None and document_date is not None
        else 999
    )
    return (
        0,
        due_difference if due_difference is not None else 999,
        min(event_difference if event_difference is not None else 999, doc_difference),
    )


def _statement_reference_reason(
    *,
    reference: str,
    context: dict[str, int | None] | None,
    transaction_date: date | None,
) -> str:
    if context is None:
        return f"Referenced by a supplier statement as invoice {reference}"
    if context.get("due_date_difference") == 0:
        return f"Referenced by a supplier statement; due date for invoice {reference} matches the bank transaction date"
    if context.get("due_date_difference") is not None:
        return (
            f"Referenced by a supplier statement; due date for invoice {reference} is "
            f"{context['due_date_difference']} day(s) from the bank transaction"
        )
    if context.get("event_date_difference") is not None:
        return (
            f"Referenced by a supplier statement; invoice {reference} is "
            f"{context['event_date_difference']} day(s) from the bank transaction"
        )
    return f"Referenced by a supplier statement as invoice {reference}"


def _document_score_from_analysis(
    document_id: uuid.UUID,
    analysis: ReconciliationTransactionItem,
    persisted_links: list[TransactionDocumentLink],
) -> float | None:
    for match in [*analysis.exact_matches, *analysis.suggested_matches, *analysis.supporting_matches]:
        if match.document_id == document_id:
            return match.score
    for link in persisted_links:
        if link.document_id == document_id:
            return link.score
    return None


def _document_reason_from_analysis(
    document_id: uuid.UUID,
    analysis: ReconciliationTransactionItem,
    persisted_links: list[TransactionDocumentLink],
) -> str | None:
    for match in [*analysis.exact_matches, *analysis.suggested_matches, *analysis.supporting_matches]:
        if match.document_id == document_id:
            return match.reason
    for link in persisted_links:
        if link.document_id == document_id:
            return link.match_reason
    return None


def _build_supplier_stage_summary(
    *,
    transaction: Transaction,
    supplier_label: str | None,
    bank_counterparty: str | None,
) -> str:
    if supplier_label and bank_counterparty and supplier_label != bank_counterparty:
        return f"Bank payee {bank_counterparty} is being treated as supplier {supplier_label} for this review."
    if supplier_label:
        return f"The transaction is currently being reviewed under supplier {supplier_label}."
    if bank_counterparty:
        return f"The current supplier clue is the bank payee {bank_counterparty}."
    return "No supplier clue has been resolved yet."


def _build_statement_stage_summary(
    *,
    statement_documents: list[ReconciliationFlowDocument],
    settlements: list[ReconciliationFlowSettlement],
    statement_invoice_refs: list[str],
    statement_payment_refs: list[str],
    statements_missing_amounts: bool,
) -> str:
    if settlements:
        return (
            f"{len(statement_documents)} statement document(s) already produce "
            f"{len(settlements)} payment-to-invoice settlement group(s) for this row."
        )
    if statement_documents and (statement_invoice_refs or statement_payment_refs):
        if statements_missing_amounts:
            return (
                f"{len(statement_documents)} statement document(s) were found and they reference "
                f"{len(statement_invoice_refs)} invoice line(s), but some line amounts are missing so the payment group is incomplete."
            )
        return (
            f"{len(statement_documents)} statement document(s) were found and they reference "
            f"{len(statement_invoice_refs)} invoice line(s) and {len(statement_payment_refs)} payment line(s)."
        )
    if statement_documents:
        return f"{len(statement_documents)} supporting statement document(s) were found for this supplier-period."
    return "No financial statement document has been tied to this payment yet."


def _build_component_stage_summary(
    *,
    component_documents: list[ReconciliationFlowDocument],
    missing_invoice_refs: list[str],
    missing_credit_refs: list[str],
    settlements: list[ReconciliationFlowSettlement],
) -> str:
    if settlements and component_documents and not missing_invoice_refs and not missing_credit_refs:
        return "The imported invoices and credit notes line up with the statement settlement."
    if component_documents and (missing_invoice_refs or missing_credit_refs):
        return "Some invoice or credit-note documents are linked, but the statement still references missing components."
    if component_documents:
        return "Imported invoices or credit notes are already available for this payment window."
    if missing_invoice_refs or missing_credit_refs:
        return "The statement references invoices or credits that are not yet fully present in the imported document set."
    return "No invoice or credit-note component has been tied to this row yet."


def _action_stage_status(resolution_bucket: str) -> str:
    return {
        "confirm_match": "ready",
        "complete_partial_match": "partial",
        "review_supporting_docs": "partial",
        "awaiting_document": "missing",
        "needs_matcher_improvement": "partial",
        "no_document_expected": "resolved",
    }.get(resolution_bucket, "partial")


def _next_step_for_flow(
    *,
    transaction: Transaction,
    analysis: ReconciliationTransactionItem,
    settlements: list[ReconciliationFlowSettlement],
    statement_documents: list[ReconciliationFlowDocument],
    missing_invoice_refs: list[str],
    missing_credit_refs: list[str],
    statements_missing_amounts: bool,
) -> str:
    if analysis.resolution_bucket == "confirm_match":
        return "Confirm the invoice coverage shown for this row."
    if settlements:
        return "Use the statement-backed settlement group as the primary review path, then confirm the supporting invoice coverage."
    if statement_documents and statements_missing_amounts:
        return "Re-extract or inspect the statement with better table recovery; the refs are there, but the line amounts are not complete enough yet."
    if statement_documents and (missing_invoice_refs or missing_credit_refs):
        missing_bits = [*missing_invoice_refs[:4], *missing_credit_refs[:4]]
        return (
            "Import or extract the missing statement-referenced components, then reopen this row"
            + (f": {', '.join(missing_bits)}." if missing_bits else ".")
        )
    if analysis.resolution_bucket == "review_supporting_docs":
        return "Review the supplier statement or support docs first; only resolve it as support-only if they clearly explain the payment."
    if analysis.resolution_bucket == "awaiting_document":
        return "Treat this as a missing-evidence row until the right invoice or statement is imported."
    if analysis.resolution_bucket == "no_document_expected":
        return "No supplier document is expected for this row."
    return "Review the evidence chain from supplier to statement to invoice before resolving the row."


def _flow_role_rank(role: str | None) -> int:
    return {
        "invoice_candidate": 0,
        "statement_reference": 1,
        "statement_credit_reference": 2,
    }.get(role or "", 3)


def _ordered_unique(values: list[str] | list[uuid.UUID]) -> list:
    seen = set()
    ordered = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _primary_invoice_entry(ledger: ParsedDocumentLedger) -> ParsedLedgerEntry | None:
    invoice_entries = [entry for entry in ledger.entries if entry.entry_kind == LEDGER_ENTRY_INVOICE]
    if not invoice_entries:
        return None
    invoice_entries.sort(
        key=lambda entry: (
            entry.event_date or date.max,
            entry.reference or "",
        )
    )
    return invoice_entries[0]


def _ledger_invoice_references(ledger: ParsedDocumentLedger) -> list[str]:
    return [
        entry.reference
        for entry in ledger.entries
        if entry.entry_kind == LEDGER_ENTRY_INVOICE and entry.reference
    ]


def _ledger_payment_references(ledger: ParsedDocumentLedger) -> list[str]:
    return [
        entry.reference
        for entry in ledger.entries
        if entry.entry_kind == LEDGER_ENTRY_PAYMENT and entry.reference
    ]


def _build_ledger_supplier_keys(ledger: ParsedDocumentLedger) -> set[str]:
    if not ledger.supplier:
        return set()
    return build_supplier_lookup_keys(ledger.supplier)


def _ledger_entry_label(entry_kind: str) -> str:
    return {
        LEDGER_ENTRY_INVOICE: "invoice",
        LEDGER_ENTRY_CREDIT_NOTE: "credit_note",
        LEDGER_ENTRY_PAYMENT: "payment",
    }.get(entry_kind, "statement")


def _describe_settlement_components(settlement: LedgerSettlement) -> str:
    component_bits: list[str] = []
    for component in settlement.component_entries:
        amount = component.amount if component.entry_kind != LEDGER_ENTRY_CREDIT_NOTE else component.signed_amount
        formatted_amount = f"{amount}" if amount is not None else "unknown amount"
        reference = component.reference or component.related_reference or "unknown ref"
        component_bits.append(
            f"{_ledger_entry_label(component.entry_kind)} {reference} ({formatted_amount})"
        )
    return ", ".join(component_bits[:6]) or "statement components"


@dataclass(slots=True)
class _FuzzyStatementAmountHit:
    reference: str | None
    keywords: set[str]
    context: str


def _find_fuzzy_statement_amount_contexts(
    *,
    ledger: ParsedDocumentLedger,
    amount: Decimal | None,
) -> list[_FuzzyStatementAmountHit]:
    if amount is None or not ledger.source_text or not ledger.is_financial:
        return []

    amount_variants = _amount_string_variants(amount)
    text = ledger.source_text
    lower_text = text.lower()
    hits: list[_FuzzyStatementAmountHit] = []
    seen_contexts: set[str] = set()

    for token in amount_variants:
        start_index = 0
        token_lower = token.lower()
        while True:
            index = lower_text.find(token_lower, start_index)
            if index == -1:
                break
            context_start = max(0, index - 120)
            context_end = min(len(text), index + 120)
            context = text[context_start:context_end]
            normalized_context = " ".join(context.split())
            keywords = {
                keyword
                for keyword in ("receipt", "payment", "invoice", "credit", "b/fwd", "dd-")
                if keyword in normalized_context.lower()
            }
            reference_match = re.search(r"\bDD-\d{2}-\d{2}\b", normalized_context)
            if keywords and normalized_context not in seen_contexts:
                seen_contexts.add(normalized_context)
                hits.append(
                    _FuzzyStatementAmountHit(
                        reference=reference_match.group(0) if reference_match else None,
                        keywords=keywords,
                        context=normalized_context,
                    )
                )
            start_index = index + 1

    hits.sort(
        key=lambda hit: (
            -len(hit.keywords),
            0 if hit.reference and hit.reference.startswith("DD-") else 1,
            hit.reference or "",
        )
    )
    return hits


def _amount_string_variants(amount: Decimal) -> set[str]:
    normalized = f"{amount:.2f}"
    whole, fractional = normalized.split(".")
    return {
        normalized,
        f"{int(whole):,}.{fractional}",
    }


def _looks_like_no_document_expected(transaction: Transaction) -> bool:
    description = " ".join(
        part
        for part in (
            transaction.description1,
            transaction.description2,
            transaction.category,
        )
        if part
    )
    if not description:
        return False
    return any(pattern.search(description) for pattern in NO_DOCUMENT_EXPECTED_PATTERNS)


def _looks_like_individual_payment(transaction: Transaction) -> bool:
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE:
        return False
    if not transaction.description1 or not INDIVIDUAL_PAYMENT_PREFIX_PATTERN.search(transaction.description1):
        return False
    if transaction.expected_supplier:
        return False

    counterparty = _clean_bank_statement_counterparty(transaction.description1)
    if not counterparty:
        return False
    return match_supplier_profile(counterparty) is None


def _has_related_supplier_documents(
    *,
    transaction: Transaction,
    invoice_documents: list[Document],
    supporting_documents: list[Document],
) -> bool:
    if transaction.transaction_date is None:
        return False
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE:
        return False

    transaction_tokens = _build_transaction_tokens(transaction)
    combined_documents = [*invoice_documents, *supporting_documents]
    related_count = 0
    for document in combined_documents:
        if document.document_date is None:
            continue
        if abs((transaction.transaction_date - document.document_date).days) > 75:
            continue

        overlap = transaction_tokens & _build_document_tokens(document)
        supplier_matches, _ = _supplier_compatibility(
            transaction=transaction,
            document=document,
            overlap=overlap,
        )
        if supplier_matches:
            related_count += 1
            if related_count >= 1:
                return True

    return False


def _has_generic_annotations_only(transaction: Transaction) -> bool:
    annotation_notes = [note.strip().lower() for note in (transaction.annotation_notes or []) if note]
    if not annotation_notes:
        return False

    generic_prefixes = {
        "invoice",
        "statement",
        "receipt",
        "credit note",
    }
    return all(
        any(note == prefix or note.startswith(f"{prefix} - hard copy available") for prefix in generic_prefixes)
        for note in annotation_notes
    )


def _sum_match_amounts(matches: list[ReconciliationDocumentMatch]) -> Decimal | None:
    amounts = [match.amount for match in matches if match.amount is not None]
    if not amounts:
        return None
    return sum(amounts, Decimal("0"))


def _amounts_balance(transaction_amount: Decimal | None, matched_amount: Decimal | None) -> bool:
    if transaction_amount is None or matched_amount is None:
        return False
    return transaction_amount == matched_amount


def _status_rank(status: str) -> int:
    return {
        "matched": 0,
        "partial": 1,
        "suggested": 2,
        "unmatched": 3,
    }.get(status, 4)


def _max_score(matches: list[ReconciliationDocumentMatch]) -> float:
    if not matches:
        return 0.0
    return max(match.score or 0.0 for match in matches)


def _date_score(date_difference: int) -> float:
    if date_difference <= 7:
        return 0.2
    if date_difference <= 14:
        return 0.15
    if date_difference <= 31:
        return 0.1
    return 0.05


def _token_overlap_score(overlap: set[str]) -> float:
    if not overlap:
        return 0.0
    if len(overlap) >= 2:
        return 0.2
    return 0.1


def _tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 3
    }


def _supplier_compatibility(
    *,
    transaction: Transaction,
    document: Document,
    overlap: set[str],
) -> tuple[bool, str | None]:
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE and overlap:
        return True, "Supplier or file metadata overlaps with transaction text"

    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE:
        return False, None

    transaction_supplier_keys = _build_transaction_supplier_keys(transaction)
    document_supplier_keys = _build_document_supplier_keys(document)
    if _supplier_keys_overlap(transaction_supplier_keys, document_supplier_keys):
        return True, "Bank payee aligns with the supplier"

    significant_overlap = _meaningful_overlap_tokens(overlap)
    if significant_overlap:
        return True, f"Supplier metadata overlaps with the bank payee ({', '.join(sorted(significant_overlap))})"

    return False, None


def _build_transaction_supplier_keys(transaction: Transaction) -> set[str]:
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE:
        return set()

    supplier_keys: set[str] = set()

    counterparty = _clean_bank_statement_counterparty(transaction.description1)
    if counterparty:
        supplier_keys.update(build_supplier_lookup_keys(counterparty))
    if transaction.expected_supplier:
        supplier_keys.update(build_supplier_lookup_keys(transaction.expected_supplier))
    return supplier_keys


def _build_document_supplier_keys(document: Document) -> set[str]:
    if not document.supplier:
        return set()
    return build_supplier_lookup_keys(document.supplier)


def _pub_compatibility(
    *,
    transaction: Transaction,
    document: Document,
) -> tuple[bool, bool, str | None]:
    transaction_pub_keys = _build_transaction_pub_keys(transaction)
    document_pub_keys = _build_document_pub_keys(document)
    if not transaction_pub_keys or not document_pub_keys:
        return False, False, None
    if transaction_pub_keys & document_pub_keys:
        return True, False, "Document venue aligns with the transaction pub"
    return False, True, "Document venue points to a different pub"


def _build_transaction_pub_keys(transaction: Transaction) -> set[str]:
    return _extract_pub_keys_from_aliases(
        TRANSACTION_PUB_ALIASES,
        transaction.pub,
        transaction.category,
    )


def _build_document_pub_keys(document: Document) -> set[str]:
    pub_keys = _extract_pub_keys_from_document_metadata(document)
    pub_keys.update(_extract_pub_keys_from_recipient_context(document.extracted_text))
    pub_keys.update(_extract_pub_keys_from_statement_context(document.extracted_text))
    pub_keys.update(_extract_pub_keys_from_lead_context(document.extracted_text))
    return pub_keys


def _extract_pub_keys_from_document_metadata(document: Document) -> set[str]:
    metadata_values = [document.attachment_name]
    if document.source_email_sender == "local-archive":
        metadata_values.extend(
            [
                document.source_email_subject,
                document.local_path,
                document.drive_folder_path,
            ]
        )
    return _extract_pub_keys_from_aliases(DOCUMENT_METADATA_PUB_ALIASES, *metadata_values)


def _extract_pub_keys_from_recipient_context(text: str | None) -> set[str]:
    if not text:
        return set()

    lines = [line.strip() for line in text.splitlines()]
    recipient_blocks: list[str] = []
    for index, line in enumerate(lines):
        normalized_line = line.lower().rstrip(":")
        if normalized_line not in DOCUMENT_RECIPIENT_LABELS:
            continue

        block_lines: list[str] = []
        for candidate in lines[index + 1 : index + 7]:
            if not candidate:
                if block_lines:
                    break
                continue
            block_lines.append(candidate)
        if block_lines:
            recipient_blocks.append(" ".join(block_lines))

    return _extract_pub_keys_from_aliases(
        DOCUMENT_RECIPIENT_PUB_ALIASES,
        *recipient_blocks,
    )


def _extract_pub_keys_from_statement_context(text: str | None) -> set[str]:
    if not text:
        return set()

    lines = [line.strip() for line in text.splitlines()]
    statement_blocks: list[str] = []
    for index, line in enumerate(lines):
        normalized_line = line.lower().rstrip(":")
        if normalized_line not in DOCUMENT_STATEMENT_ADDRESS_LABELS:
            continue

        block_lines: list[str] = []
        for candidate in lines[index + 1 : index + 8]:
            if not candidate:
                if block_lines:
                    break
                continue
            lower_candidate = candidate.lower().rstrip(":")
            if lower_candidate in {
                "correspondence address",
                "details",
                "doc",
                "date",
                "page",
                "quantity details € unit price € net amount",
            }:
                break
            block_lines.append(candidate)
        if block_lines:
            statement_blocks.append(" ".join(block_lines))

    return _extract_pub_keys_from_aliases(
        DOCUMENT_STATEMENT_PUB_ALIASES,
        *statement_blocks,
    )


def _extract_pub_keys_from_lead_context(text: str | None) -> set[str]:
    if not text:
        return set()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return set()

    lead_lines: list[str] = []
    stop_markers = {
        "date",
        "reference",
        "your ref",
        "order no.",
        "order no",
        "type",
        "doc",
        "billing doc",
        "quantity details € unit price € net amount",
    }
    for line in lines[:20]:
        normalized = line.lower().rstrip(":")
        if normalized in stop_markers:
            break
        lead_lines.append(line)

    return _extract_pub_keys_from_aliases(
        DOCUMENT_STATEMENT_PUB_ALIASES,
        " ".join(lead_lines),
    )


def _extract_pub_keys_from_aliases(
    alias_map: dict[str, set[str]],
    *values: str | None,
) -> set[str]:
    compact_values = [_compact_supplier_key(value) for value in values if value]
    pub_keys: set[str] = set()
    for canonical_key, aliases in alias_map.items():
        for alias in aliases:
            if any(alias in compact_value for compact_value in compact_values):
                pub_keys.add(canonical_key)
                break
    return pub_keys


def _expand_supplier_alias_keys(keys: set[str]) -> set[str]:
    expanded = {key for key in keys if key}
    for key in list(expanded):
        expanded.update(build_supplier_lookup_keys(key))
    return expanded


def _supplier_keys_overlap(left_keys: set[str], right_keys: set[str]) -> bool:
    if not left_keys or not right_keys:
        return False

    return any(
        _supplier_keys_match(left_key, right_key)
        for left_key in left_keys
        for right_key in right_keys
    )


def _supplier_keys_match(left_key: str, right_key: str) -> bool:
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True

    min_length = min(len(left_key), len(right_key))
    if min_length < 8:
        return False
    return left_key.startswith(right_key) or right_key.startswith(left_key)


def _clean_bank_statement_counterparty(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = value.strip()
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = BANK_STATEMENT_COUNTERPARTY_PREFIX_PATTERN.sub("", cleaned).strip(" -")

    return cleaned or None


def _compact_supplier_key(value: str | None) -> str:
    return compact_profile_key(value)


def _meaningful_overlap_tokens(overlap: set[str]) -> set[str]:
    return {
        token
        for token in overlap
        if len(token) >= 5 and token not in GENERIC_SUPPLIER_TOKENS
    }
