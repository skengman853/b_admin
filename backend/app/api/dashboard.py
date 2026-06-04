from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import User, Invoice, Document, Transaction
from app.schemas import (
    DashboardSummary,
    DocumentStorageSummaryResponse,
    StatementWorkbenchItemResponse,
    StatementWorkbenchResponse,
    StatementWorkbenchSettlementComponentResponse,
    StatementWorkbenchSettlementResponse,
    StatementWorkbenchTransactionResponse,
    SupplierDocumentInventoryItemResponse,
    SupplierDocumentInventoryResponse,
    SupplierOptionResponse,
    SupplierOptionsResponse,
)
from app.services.document_ledger import (
    LEDGER_ENTRY_CREDIT_NOTE,
    LEDGER_ENTRY_INVOICE,
    LEDGER_ENTRY_PAYMENT,
    build_document_ledger,
    build_statement_settlements,
    find_matching_ledger_entries,
)
from app.services.invoice_projection import sync_invoices_from_documents
from app.services.supplier_profiles import canonicalize_supplier_name, build_supplier_lookup_keys
from app.services.transaction_reconciliation import _clean_bank_statement_counterparty

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
MONTH_TOKEN_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def _month_bounds(month: str) -> tuple[date, date]:
    year, m = int(month[:4]), int(month[5:7])
    start = date(year, m, 1)
    end = date(year, m + 1, 1) if m < 12 else date(year + 1, 1, 1)
    return start, end


def _shift_month(month: str, offset: int) -> str:
    year, m = int(month[:4]), int(month[5:7])
    total = year * 12 + (m - 1) + offset
    shifted_year = total // 12
    shifted_month = (total % 12) + 1
    return f"{shifted_year:04d}-{shifted_month:02d}"


def _month_window(month: str, window_months: int) -> tuple[date, date]:
    start_month = _shift_month(month, -window_months)
    end_month = _shift_month(month, window_months)
    start, _ = _month_bounds(start_month)
    _, end = _month_bounds(end_month)
    return start, end


def _parse_selected_months(months: str | None) -> list[str]:
    if not months:
        return []
    values = []
    for raw in months.split(","):
        value = raw.strip()
        if not value or not MONTH_TOKEN_PATTERN.fullmatch(value):
            continue
        values.append(value)
    return list(dict.fromkeys(values))


def _document_pub_hint(document: Document) -> str | None:
    haystacks = [
        document.local_path or "",
        document.drive_folder_path or "",
        document.attachment_name or "",
        document.source_email_subject or "",
        document.extracted_text or "",
    ]
    lowered = " ".join(haystacks).lower()
    if any(token in lowered for token in ("careys", "careys pub", "careys tavern", "car18", "carey01", "mardyke")):
        return "Careys"
    if any(token in lowered for token in ("canal", "canal turn", "can02", "cana01", "ballymahon")):
        return "Canal"
    if "corrcross" in lowered:
        return "Corrcross"
    return None


def _matches_supplier_inventory_query(document: Document, supplier_query: str) -> tuple[bool, str | None]:
    query_keys = build_supplier_lookup_keys(supplier_query)
    document_keys = build_supplier_lookup_keys(document.supplier)
    if query_keys and document_keys and query_keys & document_keys:
        return True, canonicalize_supplier_name(document.supplier)

    query_token = "".join(ch for ch in supplier_query.lower() if ch.isalnum())
    document_token = "".join(ch for ch in (document.supplier or "").lower() if ch.isalnum())
    if query_token and document_token and (query_token in document_token or document_token in query_token):
        return True, canonicalize_supplier_name(document.supplier)
    return False, None


def _document_storage_state(document: Document) -> str:
    has_r2 = bool(document.storage_provider == "s3" and document.storage_key)
    has_drive = bool(document.drive_file_id)
    if has_r2 and has_drive:
        return "r2_and_drive"
    if has_r2:
        return "r2_only"
    if has_drive:
        return "drive_only"
    return "local_only"


def _document_matches_filters(
    document: Document,
    *,
    month: str | None,
    selected_months: list[str],
    pub: str | None,
    window_months: int,
) -> bool:
    if selected_months and document.document_date is not None:
        if document.document_date.strftime("%Y-%m") not in selected_months:
            return False
    elif month:
        start, end = _month_window(month, window_months)
        if document.document_date is not None and not (start <= document.document_date < end):
            return False

    pub_hint = _document_pub_hint(document)
    if pub and pub_hint and pub_hint.lower() != pub.lower():
        return False
    return True


def _normalize_reference_token(reference: str | None) -> str | None:
    if reference is None:
        return None
    value = reference.strip()
    if not value:
        return None
    normalized = re.sub(r"\s+", " ", value).upper()
    if normalized.isdigit():
        return normalized.lstrip("0") or "0"
    return normalized


def _transaction_matches_supplier(statement_supplier: str, transaction: Transaction) -> bool:
    supplier_keys = build_supplier_lookup_keys(statement_supplier)
    transaction_counterparty = (
        _clean_bank_statement_counterparty(transaction.description1)
        or transaction.expected_supplier
        or transaction.description1
        or ""
    )
    transaction_keys = build_supplier_lookup_keys(transaction_counterparty)
    return bool(supplier_keys and transaction_keys and supplier_keys & transaction_keys)


def _transaction_matches_filters(
    transaction: Transaction,
    *,
    month: str | None,
    selected_months: list[str],
    pub: str | None,
    window_months: int,
) -> bool:
    if selected_months and transaction.transaction_date is not None:
        if transaction.transaction_date.strftime("%Y-%m") not in selected_months:
            return False
    elif month and transaction.transaction_date is not None:
        start, end = _month_window(month, window_months)
        if not (start <= transaction.transaction_date < end):
            return False

    if pub and (transaction.pub or "").lower() != pub.lower():
        return False
    return True


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    month: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await sync_invoices_from_documents(db=db, user_id=user.id)
    await db.commit()

    now = datetime.utcnow()
    if month:
        year, m = int(month[:4]), int(month[5:7])
    else:
        year, m = now.year, now.month
        month = f"{year}-{m:02d}"

    start = date(year, m, 1)
    end = date(year, m + 1, 1) if m < 12 else date(year + 1, 1, 1)

    base = select(Invoice).where(
        Invoice.user_id == user.id,
        Invoice.invoice_date >= start,
        Invoice.invoice_date < end,
        Invoice.status != "rejected",
    )

    total_result = await db.execute(
        select(func.coalesce(func.sum(Invoice.amount), 0)).where(
            Invoice.user_id == user.id,
            Invoice.invoice_date >= start,
            Invoice.invoice_date < end,
            Invoice.status != "rejected",
        )
    )
    total_spend = total_result.scalar() or Decimal("0")

    count_result = await db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.user_id == user.id,
            Invoice.invoice_date >= start,
            Invoice.invoice_date < end,
            Invoice.status != "rejected",
        )
    )
    invoice_count = count_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.user_id == user.id,
            Invoice.invoice_date >= start,
            Invoice.invoice_date < end,
            Invoice.status == "pending",
        )
    )
    pending_review = pending_result.scalar() or 0

    return DashboardSummary(
        month=month,
        total_spend=total_spend,
        invoice_count=invoice_count,
        pending_review=pending_review,
    )


@router.get("/document-inventory", response_model=SupplierDocumentInventoryResponse)
async def get_supplier_document_inventory(
    supplier: str,
    month: str | None = None,
    months: str | None = None,
    pub: str | None = None,
    window_months: int = Query(1, ge=0, le=3),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    supplier_query = " ".join((supplier or "").split()).strip()
    canonical_supplier = canonicalize_supplier_name(supplier_query)
    selected_months = _parse_selected_months(months)

    query = select(Document).where(
        Document.user_id == user.id,
        Document.extraction_status != "split",
    )
    if month and not selected_months:
        start, end = _month_window(month, window_months)
        query = query.where(
            (Document.document_date.is_(None)) | ((Document.document_date >= start) & (Document.document_date < end))
        )

    result = await db.execute(
        query.order_by(
            Document.document_date.asc().nulls_last(),
            Document.created_at.asc(),
        )
    )
    candidate_documents = list(result.scalars().all())

    matched_documents: list[Document] = []
    available_months: set[str] = set()
    counts_by_type: Counter[str] = Counter()
    counts_by_storage: Counter[str] = Counter()

    for document in candidate_documents:
        matches, resolved_canonical = _matches_supplier_inventory_query(document, supplier_query)
        if not matches:
            continue
        if not _document_matches_filters(
            document,
            month=month,
            selected_months=selected_months,
            pub=pub,
            window_months=window_months,
        ):
            continue
        matched_documents.append(document)
        counts_by_type[document.document_type or "unknown"] += 1
        counts_by_storage[_document_storage_state(document)] += 1
        if document.document_date is not None:
            available_months.add(document.document_date.strftime("%Y-%m"))

    limited_documents = matched_documents[:limit]
    return SupplierDocumentInventoryResponse(
        supplier_query=supplier_query,
        canonical_supplier=canonical_supplier,
        month=month,
        selected_months=selected_months,
        window_months=window_months,
        total_documents=len(matched_documents),
        counts_by_type=dict(counts_by_type),
        counts_by_storage=dict(counts_by_storage),
        available_months=sorted(available_months),
        documents=[
            SupplierDocumentInventoryItemResponse(
                id=document.id,
                supplier=document.supplier,
                canonical_supplier=canonicalize_supplier_name(document.supplier),
                document_type=document.document_type,
                document_date=document.document_date,
                reference=document.reference,
                amount=document.amount,
                extraction_status=document.extraction_status,
                needs_review=document.needs_review,
                attachment_name=document.attachment_name,
                storage_state=_document_storage_state(document),
                storage_provider=document.storage_provider,
                storage_bucket=document.storage_bucket,
                storage_key=document.storage_key,
                local_path=document.local_path,
                drive_file_id=document.drive_file_id,
                drive_web_link=document.drive_web_link,
                drive_folder_path=document.drive_folder_path,
                source_email_subject=document.source_email_subject,
                pub_hint=_document_pub_hint(document),
            )
            for document in limited_documents
        ],
    )


@router.get("/storage-summary", response_model=DocumentStorageSummaryResponse)
async def get_document_storage_summary(
    month: str | None = None,
    months: str | None = None,
    pub: str | None = None,
    window_months: int = Query(1, ge=0, le=3),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    selected_months = _parse_selected_months(months)
    query = select(Document).where(
        Document.user_id == user.id,
        Document.extraction_status != "split",
    )
    if month and not selected_months:
        start, end = _month_window(month, window_months)
        query = query.where(
            (Document.document_date.is_(None)) | ((Document.document_date >= start) & (Document.document_date < end))
        )

    result = await db.execute(query)
    documents = list(result.scalars().all())

    counts = Counter()
    total_documents = 0
    for document in documents:
        if not _document_matches_filters(
            document,
            month=month,
            selected_months=selected_months,
            pub=pub,
            window_months=window_months,
        ):
            continue
        counts[_document_storage_state(document)] += 1
        total_documents += 1

    return DocumentStorageSummaryResponse(
        month=month,
        selected_months=selected_months,
        window_months=window_months,
        pub=pub,
        total_documents=total_documents,
        local_only=counts.get("local_only", 0),
        r2_only=counts.get("r2_only", 0),
        drive_only=counts.get("drive_only", 0),
        r2_and_drive=counts.get("r2_and_drive", 0),
    )


@router.get("/statement-workbench", response_model=StatementWorkbenchResponse)
async def get_statement_workbench(
    supplier: str,
    month: str | None = None,
    months: str | None = None,
    pub: str | None = None,
    window_months: int = Query(1, ge=0, le=3),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    supplier_query = " ".join((supplier or "").split()).strip()
    canonical_supplier = canonicalize_supplier_name(supplier_query) if supplier_query else None
    selected_months = _parse_selected_months(months)
    if not supplier_query:
        return StatementWorkbenchResponse(
            supplier_query="",
            canonical_supplier=None,
            month=month,
            selected_months=selected_months,
            window_months=window_months,
            pub=pub,
        )

    document_query = select(Document).where(
        Document.user_id == user.id,
        Document.extraction_status != "split",
    )
    if month and not selected_months:
        start, end = _month_window(month, window_months)
        document_query = document_query.where(
            (Document.document_date.is_(None)) | ((Document.document_date >= start) & (Document.document_date < end))
        )

    transaction_query = select(Transaction).where(
        Transaction.user_id == user.id,
        Transaction.source_type == "bank_statement",
    )
    if month and not selected_months:
        start, end = _month_window(month, window_months)
        transaction_query = transaction_query.where(
            (Transaction.transaction_date.is_(None))
            | ((Transaction.transaction_date >= start) & (Transaction.transaction_date < end))
        )

    document_result = await db.execute(
        document_query.order_by(Document.document_date.asc().nulls_last(), Document.created_at.asc())
    )
    transaction_result = await db.execute(
        transaction_query.order_by(Transaction.transaction_date.asc().nulls_last(), Transaction.row_number.asc())
    )
    candidate_documents = list(document_result.scalars().all())
    candidate_transactions = list(transaction_result.scalars().all())

    supplier_documents = [
        document
        for document in candidate_documents
        if _matches_supplier_inventory_query(document, supplier_query)[0]
        and _document_matches_filters(
            document,
            month=month,
            selected_months=selected_months,
            pub=pub,
            window_months=window_months,
        )
    ]
    statement_documents = [
        document
        for document in supplier_documents
        if document.document_type == "statement"
    ][:limit]

    invoice_ref_map = {
        normalized: document.reference
        for document in supplier_documents
        if document.document_type == "invoice"
        if (normalized := _normalize_reference_token(document.reference))
    }
    credit_ref_map = {
        normalized: document.reference
        for document in supplier_documents
        if document.document_type == "credit_note"
        if (normalized := _normalize_reference_token(document.reference))
    }

    matching_transactions = [
        transaction
        for transaction in candidate_transactions
        if _transaction_matches_filters(
            transaction,
            month=month,
            selected_months=selected_months,
            pub=pub,
            window_months=window_months,
        )
        and _transaction_matches_supplier(supplier_query, transaction)
    ]

    statement_items: list[StatementWorkbenchItemResponse] = []
    statements_with_settlements = 0
    total_missing_invoice_refs = 0
    total_missing_credit_refs = 0
    total_likely_transactions = 0

    for document in statement_documents:
        ledger = build_document_ledger(document)
        if ledger is None:
            continue

        invoice_refs: list[str] = []
        credit_refs: list[str] = []
        payment_refs: list[str] = []
        for entry in ledger.entries:
            if entry.reference is None:
                continue
            if entry.entry_kind == LEDGER_ENTRY_INVOICE and entry.reference not in invoice_refs:
                invoice_refs.append(entry.reference)
            elif entry.entry_kind == LEDGER_ENTRY_CREDIT_NOTE and entry.reference not in credit_refs:
                credit_refs.append(entry.reference)
            elif entry.entry_kind == LEDGER_ENTRY_PAYMENT and entry.reference not in payment_refs:
                payment_refs.append(entry.reference)

        imported_invoice_refs = [
            reference
            for reference in invoice_refs
            if _normalize_reference_token(reference) in invoice_ref_map
        ]
        missing_invoice_refs = [
            reference
            for reference in invoice_refs
            if _normalize_reference_token(reference) not in invoice_ref_map
        ]
        imported_credit_refs = [
            reference
            for reference in credit_refs
            if _normalize_reference_token(reference) in credit_ref_map
        ]
        missing_credit_refs = [
            reference
            for reference in credit_refs
            if _normalize_reference_token(reference) not in credit_ref_map
        ]

        settlements = build_statement_settlements(ledger)
        if settlements:
            statements_with_settlements += 1
        settlement_payloads = [
            StatementWorkbenchSettlementResponse(
                payment_reference=settlement.payment_entry.reference,
                payment_date=settlement.payment_entry.event_date,
                due_date=settlement.payment_entry.due_date,
                amount=settlement.payment_entry.amount,
                net_amount=settlement.net_amount,
                component_count=len(settlement.component_entries),
                components=[
                    StatementWorkbenchSettlementComponentResponse(
                        entry_kind=component.entry_kind,
                        reference=component.reference,
                        related_reference=component.related_reference,
                        event_date=component.event_date,
                        due_date=component.due_date,
                        amount=component.amount,
                    )
                    for component in settlement.component_entries
                ],
            )
            for settlement in settlements
        ]

        likely_transactions: list[StatementWorkbenchTransactionResponse] = []
        transaction_candidates: list[tuple[int, int, StatementWorkbenchTransactionResponse]] = []
        for transaction in matching_transactions:
            score = 0
            reasons: list[str] = []
            transaction_amount = transaction.debit_amount
            exact_statement_lines = []
            if settlements and transaction_amount is not None:
                for settlement in settlements:
                    if settlement.payment_entry.amount == transaction_amount:
                        score += 4
                        if settlement.payment_entry.reference:
                            reasons.append(
                                f"Matches statement payment {settlement.payment_entry.reference} amount {settlement.payment_entry.amount}"
                            )
                        else:
                            reasons.append(f"Matches statement settlement amount {settlement.payment_entry.amount}")
                        payment_date = settlement.payment_entry.event_date or settlement.payment_entry.due_date
                        if payment_date is not None and transaction.transaction_date is not None:
                            score += 1
                            reasons.append(
                                f"{abs((transaction.transaction_date - payment_date).days)} day(s) from statement payment date"
                            )
                        break

            if transaction_amount is not None:
                exact_statement_lines = find_matching_ledger_entries(
                    entries=ledger.entries,
                    amount=transaction_amount,
                    entry_kinds={LEDGER_ENTRY_PAYMENT, LEDGER_ENTRY_INVOICE, LEDGER_ENTRY_CREDIT_NOTE},
                )
                if exact_statement_lines:
                    score += 3
                    reasons.append(
                        f"Statement contains {len(exact_statement_lines)} line(s) at {transaction_amount}"
                    )

            if ledger.period_start is not None and ledger.period_end is not None and transaction.transaction_date is not None:
                if ledger.period_start <= transaction.transaction_date <= ledger.period_end:
                    score += 2
                    reasons.append("Transaction date falls inside the statement period")
                elif transaction.transaction_date > ledger.period_end:
                    day_gap = (transaction.transaction_date - ledger.period_end).days
                    if day_gap <= 7:
                        score += 1
                        reasons.append(f"Transaction date is {day_gap} day(s) after the statement period end")
            elif document.document_date is not None and transaction.transaction_date is not None:
                day_gap = abs((transaction.transaction_date - document.document_date).days)
                if day_gap <= 5:
                    score += 1
                    reasons.append(f"Transaction date is {day_gap} day(s) from the statement date")

            if not score:
                continue
            transaction_candidates.append(
                (
                    -score,
                    abs((transaction.transaction_date - (document.document_date or transaction.transaction_date)).days)
                    if transaction.transaction_date is not None
                    else 999,
                    StatementWorkbenchTransactionResponse(
                        id=transaction.id,
                        row_number=transaction.row_number,
                        transaction_date=transaction.transaction_date,
                        description1=transaction.description1,
                        pub=transaction.pub,
                        debit_amount=transaction.debit_amount,
                        credit_amount=transaction.credit_amount,
                        review_status=transaction.review_status,
                        reason="; ".join(reasons),
                    ),
                )
            )

        transaction_candidates.sort(key=lambda item: (item[0], item[1], item[2].row_number))
        likely_transactions = [item[2] for item in transaction_candidates[:6]]

        total_missing_invoice_refs += len(missing_invoice_refs)
        total_missing_credit_refs += len(missing_credit_refs)
        total_likely_transactions += len(likely_transactions)

        statement_items.append(
            StatementWorkbenchItemResponse(
                id=document.id,
                supplier=document.supplier,
                canonical_supplier=canonicalize_supplier_name(document.supplier),
                statement_kind=ledger.statement_kind,
                document_date=document.document_date,
                reference=document.reference,
                amount=document.amount,
                account_number=ledger.account_number,
                account_name=ledger.account_name,
                period_start=ledger.period_start,
                period_end=ledger.period_end,
                note=ledger.note,
                invoice_refs=invoice_refs,
                credit_refs=credit_refs,
                payment_refs=payment_refs,
                imported_invoice_refs=imported_invoice_refs,
                missing_invoice_refs=missing_invoice_refs,
                imported_credit_refs=imported_credit_refs,
                missing_credit_refs=missing_credit_refs,
                settlement_count=len(settlement_payloads),
                settlements=settlement_payloads,
                likely_transactions=likely_transactions,
                storage_state=_document_storage_state(document),
                storage_provider=document.storage_provider,
                storage_bucket=document.storage_bucket,
                storage_key=document.storage_key,
                drive_file_id=document.drive_file_id,
                drive_web_link=document.drive_web_link,
                pub_hint=_document_pub_hint(document),
            )
        )

    return StatementWorkbenchResponse(
        supplier_query=supplier_query,
        canonical_supplier=canonical_supplier,
        month=month,
        selected_months=selected_months,
        window_months=window_months,
        pub=pub,
        total_statements=len(statement_items),
        statements_with_settlements=statements_with_settlements,
        total_missing_invoice_refs=total_missing_invoice_refs,
        total_missing_credit_refs=total_missing_credit_refs,
        total_likely_transactions=total_likely_transactions,
        statements=statement_items,
    )


@router.get("/suppliers", response_model=SupplierOptionsResponse)
async def list_suppliers(
    pub: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Document).where(
        Document.user_id == user.id,
        Document.extraction_status != "split",
    )
    result = await db.execute(query)
    documents = list(result.scalars().all())

    counts_by_supplier: dict[str, int] = {}
    canonical_by_supplier: dict[str, str | None] = {}

    for document in documents:
        supplier_name = " ".join((document.supplier or "").split()).strip()
        if not supplier_name:
            continue
        pub_hint = _document_pub_hint(document)
        if pub and pub_hint and pub_hint.lower() != pub.lower():
            continue
        counts_by_supplier[supplier_name] = counts_by_supplier.get(supplier_name, 0) + 1
        canonical_by_supplier[supplier_name] = canonicalize_supplier_name(supplier_name)

    suppliers = sorted(
        [
            SupplierOptionResponse(
                supplier=supplier,
                canonical_supplier=canonical_by_supplier.get(supplier),
                document_count=count,
            )
            for supplier, count in counts_by_supplier.items()
        ],
        key=lambda item: (
            (item.canonical_supplier or item.supplier).lower(),
            item.supplier.lower(),
        ),
    )

    return SupplierOptionsResponse(suppliers=suppliers)
