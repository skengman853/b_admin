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

AUTO_EXACT_LINK_NOTE = "auto_exact_reference_note_match"
EXACT_REFERENCE_REASON = "Reference found in VAT-book annotation notes"
VALID_RECONCILIATION_STATUSES = {"matched", "partial", "suggested", "unmatched"}
DEFAULT_REVIEW_QUEUE_STATUSES = ("partial", "suggested", "unmatched")
RESOLVED_TRANSACTION_REVIEW_STATUSES = {"linked", "supporting_docs_only", "no_document_expected"}
BANK_STATEMENT_SOURCE_TYPE = "bank_statement"
BANK_STATEMENT_COUNTERPARTY_PREFIX_PATTERN = re.compile(
    r"^(?:\*?(?:inet|mobi|pos|visa|mc|card)\s+|(?:d/d|dd|vdp|vdc)\s*[- ]*)",
    re.IGNORECASE,
)
BANK_STATEMENT_SUPPLIER_ALIASES: dict[str, set[str]] = {
    "moodmaster": {"automaticamusements"},
    "nationalautom": {"automaticamusements"},
}
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
    transactions: list[ReconciliationTransactionItem] = field(default_factory=list)


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

    for transaction in report_transactions:
        item = build_transaction_reconciliation_item(
            transaction=transaction,
            documents=candidate_documents,
            supporting_documents=supporting_documents,
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

    items: list[ReconciliationTransactionItem] = [
        build_transaction_reconciliation_item(
            transaction=transaction,
            documents=candidate_documents,
            supporting_documents=supporting_documents,
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
        and (
            (transaction_by_id[item.transaction_id].review_status in review_statuses)
            if review_statuses is not None
            else transaction_by_id[item.transaction_id].review_status not in RESOLVED_TRANSACTION_REVIEW_STATUSES
        )
    ]
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
    return build_transaction_reconciliation_item(
        transaction=transaction,
        documents=candidate_documents,
        supporting_documents=supporting_documents,
    )


def build_transaction_reconciliation_item(
    *,
    transaction: Transaction,
    documents: list[Document],
    supporting_documents: list[Document] | None = None,
) -> ReconciliationTransactionItem:
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
            return item

        additional_suggestions = _find_completion_suggestions(
            transaction=transaction,
            documents=documents,
            exact_matches=exact_matches,
        )
        if additional_suggestions:
            item.status = "suggested"
            item.suggested_matches = additional_suggestions
            return item

        item.status = "partial"
        return item

    suggested_matches = _find_suggested_matches(transaction=transaction, documents=documents)
    if suggested_matches:
        item.status = "suggested"
        item.suggested_matches = suggested_matches
        return item

    support_matches = _find_supporting_document_suggestions(
        transaction=transaction,
        documents=supporting_documents or [],
    )
    if support_matches:
        item.supporting_matches = support_matches
        item.analysis_note = "Supporting supplier documents were found, but no invoice amount match was detected"
        support_payment_note = _build_support_payment_analysis(
            transaction=transaction,
            invoice_documents=documents,
            supporting_matches=support_matches,
        )
        if support_payment_note:
            item.status = "suggested"
            item.analysis_note = support_payment_note
            return item

    item.status = "unmatched"
    return item


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
        target_amount=remaining_amount,
        excluded_document_ids=excluded_document_ids,
        anchored_supplier=anchored_supplier,
        reason_prefix="Remaining amount after exact reference note matches",
    )


def _find_suggested_matches(
    *,
    transaction: Transaction,
    documents: list[Document],
) -> list[ReconciliationDocumentMatch]:
    single_matches = _find_single_document_suggestions(transaction=transaction, documents=documents)
    if single_matches:
        return single_matches

    if transaction.debit_amount is None:
        return []

    grouped_matches = _find_grouped_suggestion(
        transaction=transaction,
        documents=documents,
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
) -> list[ReconciliationDocumentMatch]:
    if transaction.debit_amount is None or transaction.transaction_date is None:
        return []

    transaction_tokens = _build_transaction_tokens(transaction)
    generic_annotation_only = _has_generic_annotations_only(transaction)
    suggestions: list[ReconciliationDocumentMatch] = []

    for document in documents:
        if document.amount != transaction.debit_amount or document.document_date is None:
            continue
        date_difference = abs((transaction.transaction_date - document.document_date).days)
        if date_difference > 60:
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
        if not generic_annotation_only and overlap:
            score += Decimal("0.05")

        if float(score) < 0.55:
            continue

        reason_parts = ["Amount matches exactly"]
        reason_parts.append(f"Invoice date is {date_difference} day(s) from the bank transaction")
        if overlap:
            reason_parts.append("Supplier or file metadata overlaps with transaction text")
        elif supplier_reason:
            reason_parts.append(supplier_reason)

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
            match.reference or "",
        ),
        reverse=True,
    )
    return suggestions[:3]


def _find_grouped_suggestion(
    *,
    transaction: Transaction,
    documents: list[Document],
    target_amount: Decimal,
    excluded_document_ids: set[uuid.UUID],
    anchored_supplier: str | None,
    reason_prefix: str,
) -> list[ReconciliationDocumentMatch]:
    if transaction.transaction_date is None or target_amount <= 0:
        return []

    transaction_tokens = _build_transaction_tokens(transaction)
    transaction_supplier_keys = _build_transaction_supplier_keys(transaction)
    candidates_by_supplier: dict[str, list[Document]] = defaultdict(list)

    for document in documents:
        if document.id in excluded_document_ids:
            continue
        if document.amount is None or document.amount <= 0 or document.amount > target_amount:
            continue
        if document.document_date is None:
            continue
        date_difference = abs((transaction.transaction_date - document.document_date).days)
        if date_difference > 60:
            continue
        if anchored_supplier and document.supplier != anchored_supplier:
            continue
        if (
            transaction.source_type == BANK_STATEMENT_SOURCE_TYPE
            and not _supplier_keys_overlap(transaction_supplier_keys, _build_document_supplier_keys(document))
        ):
            continue
        candidates_by_supplier[document.supplier].append(document)

    best_combo: tuple[list[Document], float, str] | None = None
    for supplier, supplier_documents in candidates_by_supplier.items():
        supplier_documents.sort(
            key=lambda document: (
                abs((transaction.transaction_date - document.document_date).days) if document.document_date else 999,
                document.amount or Decimal("0"),
            )
        )
        candidate_pool = supplier_documents[:8]
        for combo_size in range(2, min(len(candidate_pool), 4) + 1):
            for combo in combinations(candidate_pool, combo_size):
                combo_total = sum((document.amount or Decimal("0")) for document in combo)
                if combo_total != target_amount:
                    continue

                combo_date_difference = max(
                    abs((transaction.transaction_date - document.document_date).days)
                    for document in combo
                    if document.document_date is not None
                )
                combo_tokens = set()
                for document in combo:
                    combo_tokens.update(_build_document_tokens(document))

                overlap = transaction_tokens & combo_tokens
                score = 0.52 + _date_score(combo_date_difference) + _token_overlap_score(overlap)
                if supplier == anchored_supplier:
                    score += 0.1
                if (
                    transaction.source_type == BANK_STATEMENT_SOURCE_TYPE
                    and _supplier_keys_overlap(
                        transaction_supplier_keys,
                        _build_document_supplier_keys(combo[0]),
                    )
                ):
                    score += 0.15
                score += min(0.05 * (combo_size - 1), 0.15)

                reason = (
                    f"{reason_prefix}; {combo_size} invoice documents from {supplier} "
                    f"sum exactly to {target_amount}"
                )
                if overlap:
                    reason += "; supplier or file metadata overlaps with transaction text"
                elif transaction.source_type == BANK_STATEMENT_SOURCE_TYPE:
                    reason += "; bank payee aligns with the supplier"

                if best_combo is None or score > best_combo[1]:
                    best_combo = (list(combo), score, reason)

    if best_combo is None:
        return []

    combo_documents, score, reason = best_combo
    return [
        ReconciliationDocumentMatch(
            document_id=document.id,
            document_type=document.document_type,
            supplier=document.supplier,
            reference=document.reference,
            document_date=document.document_date,
            amount=document.amount,
            vat_amount=document.vat_amount,
            score=round(score, 2),
            reason=reason,
        )
        for document in sorted(
            combo_documents,
            key=lambda document: (
                document.document_date or date.min,
                document.reference or "",
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
) -> list[ReconciliationDocumentMatch]:
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE or transaction.transaction_date is None:
        return []

    transaction_tokens = _build_transaction_tokens(transaction)
    suggestions: list[ReconciliationDocumentMatch] = []

    for document in documents:
        if document.document_date is None:
            continue
        date_difference = abs((transaction.transaction_date - document.document_date).days)
        if date_difference > 45:
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

        score = Decimal("0.3")
        score += Decimal(str(_date_score(date_difference)))
        score += Decimal(str(_token_overlap_score(overlap)))
        reason_parts = [supplier_reason or "Supporting document aligns with the bank payee"]
        reason_parts.append(f"{document.document_type.replace('_', ' ').title()} date is {date_difference} day(s) from the bank transaction")
        if document.amount is not None and transaction.debit_amount is not None:
            amount_delta = abs(transaction.debit_amount - document.amount)
            if amount_delta == 0:
                score += Decimal("0.1")
                reason_parts.append("Support document amount matches exactly")
            elif amount_delta <= Decimal("5.00"):
                score += Decimal("0.05")
                reason_parts.append(f"Support document amount is within {amount_delta} of the bank debit")

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
    invoice_documents: list[Document],
    supporting_matches: list[ReconciliationDocumentMatch],
) -> str | None:
    if transaction.source_type != BANK_STATEMENT_SOURCE_TYPE or transaction.transaction_date is None:
        return None
    if not supporting_matches:
        return None

    primary_supplier = supporting_matches[0].supplier
    primary_supplier_keys = _expand_supplier_alias_keys({_compact_supplier_key(primary_supplier)})
    strong_support_matches = [
        match
        for match in supporting_matches
        if match.supplier == primary_supplier
        and match.document_type in {"statement", "credit_note"}
        and (match.score or 0.0) >= 0.45
    ]
    if len(strong_support_matches) < 2:
        return None

    nearby_supplier_invoices = [
        document
        for document in invoice_documents
        if document.document_date is not None
        and abs((transaction.transaction_date - document.document_date).days) <= 45
        and _supplier_keys_overlap(primary_supplier_keys, _build_document_supplier_keys(document))
    ]
    if len(nearby_supplier_invoices) < 2:
        return None

    support_doc_types = sorted({match.document_type.replace("_", " ") for match in strong_support_matches})
    support_doc_label = ", ".join(support_doc_types)
    return (
        f"Supplier payment aligns with {len(strong_support_matches)} supporting {support_doc_label} document(s) "
        f"and {len(nearby_supplier_invoices)} nearby {primary_supplier} invoice(s); "
        "likely account/statement settlement rather than a single-invoice payment"
    )


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

    counterparty = _clean_bank_statement_counterparty(transaction.description1)
    if not counterparty:
        return set()
    return _expand_supplier_alias_keys({_compact_supplier_key(counterparty)})


def _build_document_supplier_keys(document: Document) -> set[str]:
    if not document.supplier:
        return set()
    return _expand_supplier_alias_keys({_compact_supplier_key(document.supplier)})


def _expand_supplier_alias_keys(keys: set[str]) -> set[str]:
    expanded = {key for key in keys if key}
    for key in list(expanded):
        expanded.update(BANK_STATEMENT_SUPPLIER_ALIASES.get(key, set()))
        for alias, supplier_keys in BANK_STATEMENT_SUPPLIER_ALIASES.items():
            if key in supplier_keys:
                expanded.add(alias)
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
    if not value:
        return ""

    normalized = value.lower().replace("&", " and ").replace("+", " and ").replace("'", "")
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized


def _meaningful_overlap_tokens(overlap: set[str]) -> set[str]:
    return {
        token
        for token in overlap
        if len(token) >= 5 and token not in GENERIC_SUPPLIER_TOKENS
    }
