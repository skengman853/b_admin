import math
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import Document, Transaction, TransactionDocumentLink, TransactionReviewEvent, User
from app.schemas import (
    TransactionDetailResponse,
    TransactionDocumentMatchResponse,
    TransactionFlowDocumentResponse,
    TransactionFlowResponse,
    TransactionFlowSettlementResponse,
    TransactionFlowStageResponse,
    TransactionHistoryResponse,
    TransactionImportRequest,
    TransactionImportResponse,
    TransactionLinkCreateRequest,
    TransactionLinkedDocumentResponse,
    TransactionLinkResponse,
    TransactionLinksResponse,
    TransactionReviewEventResponse,
    TransactionReviewUpdateRequest,
    TransactionLinkUpdateRequest,
    TransactionListResponse,
    TransactionReconciliationItemResponse,
    TransactionReconciliationReportResponse,
    TransactionReviewQueueItemResponse,
    TransactionReviewQueueResponse,
    TransactionResponse,
)
from app.services.transaction_reconciliation import (
    VALID_RESOLUTION_BUCKETS,
    build_transaction_reconciliation_flow,
    build_reconciliation_report,
    build_transaction_review_queue,
    build_transaction_reconciliation_item,
    month_bounds,
    load_candidate_documents_for_transaction,
    load_supporting_documents_for_transaction,
    sync_exact_transaction_document_links,
)
from app.services.document_ledger import build_document_ledgers
from app.services.vatbook_import import import_transactions_from_vatbook

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
VALID_TRANSACTION_SOURCE_TYPES = {"vatbook", "bank_statement"}
VALID_TRANSACTION_REVIEW_STATUSES = {
    "pending",
    "linked",
    "supporting_docs_only",
    "awaiting_document",
    "no_document_expected",
}
RESOLVED_TRANSACTION_REVIEW_STATUSES = {
    "linked",
    "supporting_docs_only",
    "no_document_expected",
}


def _parse_month(month: str) -> tuple[date, date]:
    try:
        return month_bounds(month)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="month must be in YYYY-MM format")


def _parse_source_type(
    source_type: str | None,
    *,
    default: str | None = "vatbook",
) -> str | None:
    normalized = (source_type or default)
    if normalized is None:
        return None

    normalized = normalized.strip().lower()
    if normalized == "all":
        return None
    if normalized not in VALID_TRANSACTION_SOURCE_TYPES:
        allowed = ", ".join(sorted(VALID_TRANSACTION_SOURCE_TYPES | {"all"}))
        raise HTTPException(
            status_code=422,
            detail=f"source_type must be one of: {allowed}",
        )
    return normalized


def _build_transaction_response(transaction: Transaction) -> TransactionResponse:
    return TransactionResponse.model_validate(transaction, from_attributes=True)


def _build_transaction_review_event_response(
    event: TransactionReviewEvent,
) -> TransactionReviewEventResponse:
    return TransactionReviewEventResponse(
        id=event.id,
        transaction_id=event.transaction_id,
        event_type=event.event_type,
        actor_email=event.actor_email,
        previous_review_status=event.previous_review_status,
        current_review_status=event.current_review_status,
        document_id=event.document_id,
        link_id=event.link_id,
        payload=event.payload or {},
        created_at=event.created_at,
    )


def _parse_review_statuses(review_status: str | None) -> list[str] | None:
    if review_status is None:
        return None

    values = [value.strip().lower() for value in review_status.split(",") if value.strip()]
    invalid = [value for value in values if value not in VALID_TRANSACTION_REVIEW_STATUSES]
    if invalid:
        allowed = ", ".join(sorted(VALID_TRANSACTION_REVIEW_STATUSES))
        raise HTTPException(
            status_code=422,
            detail=f"review_status must be one of: {allowed}",
        )
    return values


def _parse_resolution_buckets(resolution_bucket: str | None) -> list[str] | None:
    if resolution_bucket is None:
        return None

    values = [value.strip().lower() for value in resolution_bucket.split(",") if value.strip()]
    invalid = [value for value in values if value not in VALID_RESOLUTION_BUCKETS]
    if invalid:
        allowed = ", ".join(sorted(VALID_RESOLUTION_BUCKETS))
        raise HTTPException(
            status_code=422,
            detail=f"resolution_bucket must be one of: {allowed}",
        )
    return values


async def _synchronize_transaction_review_state_for_link(
    *,
    db: AsyncSession,
    transaction: Transaction,
    document: Document,
    link_status: str,
    user: User,
    link: TransactionDocumentLink | None = None,
) -> None:
    previous_review_status = transaction.review_status
    if document.document_type == "invoice" and link_status == "confirmed":
        transaction.review_status = "linked"
        transaction.reviewed_at = datetime.utcnow()
        if transaction.review_note is None:
            transaction.review_note = None
        if previous_review_status != transaction.review_status:
            _append_transaction_review_event(
                db=db,
                transaction=transaction,
                user=user,
                event_type="auto_review_status_changed",
                previous_review_status=previous_review_status,
                current_review_status=transaction.review_status,
                document_id=document.id,
                link_id=link.id if link is not None else None,
                payload={
                    "reason": "confirmed_invoice_link",
                    "link_status": link_status,
                    "document_type": document.document_type,
                },
            )
        return

    if transaction.review_status != "linked":
        return

    confirmed_invoice_link_result = await db.execute(
        select(TransactionDocumentLink.id)
        .join(Document, Document.id == TransactionDocumentLink.document_id)
        .where(
            TransactionDocumentLink.transaction_id == transaction.id,
            TransactionDocumentLink.user_id == transaction.user_id,
            TransactionDocumentLink.status == "confirmed",
            Document.document_type == "invoice",
        )
        .limit(1)
    )
    if confirmed_invoice_link_result.first() is None:
        transaction.review_status = "pending"
        transaction.reviewed_at = datetime.utcnow()
        if previous_review_status != transaction.review_status:
            _append_transaction_review_event(
                db=db,
                transaction=transaction,
                user=user,
                event_type="auto_review_status_changed",
                previous_review_status=previous_review_status,
                current_review_status=transaction.review_status,
                document_id=document.id,
                link_id=link.id if link is not None else None,
                payload={
                    "reason": "no_confirmed_invoice_links_remaining",
                    "link_status": link_status,
                    "document_type": document.document_type,
                },
            )


def _append_transaction_review_event(
    *,
    db: AsyncSession,
    transaction: Transaction,
    user: User,
    event_type: str,
    previous_review_status: str | None = None,
    current_review_status: str | None = None,
    document_id: uuid.UUID | None = None,
    link_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> TransactionReviewEvent:
    event = TransactionReviewEvent(
        user_id=user.id,
        transaction_id=transaction.id,
        event_type=event_type,
        actor_email=user.email,
        previous_review_status=previous_review_status,
        current_review_status=current_review_status,
        document_id=document_id,
        link_id=link_id,
        payload=payload or {},
    )
    db.add(event)
    return event


def _build_match_response(match) -> TransactionDocumentMatchResponse:
    return TransactionDocumentMatchResponse(
        document_id=match.document_id,
        document_type=match.document_type,
        supplier=match.supplier,
        reference=match.reference,
        document_date=match.document_date,
        amount=match.amount,
        vat_amount=match.vat_amount,
        score=match.score,
        reason=match.reason,
    )


def _build_reconciliation_item_response(item) -> TransactionReconciliationItemResponse:
    return TransactionReconciliationItemResponse(
        transaction_id=item.transaction_id,
        source_type=item.source_type,
        row_number=item.row_number,
        pub=item.pub,
        transaction_date=item.transaction_date,
        description1=item.description1,
        description2=item.description2,
        category=item.category,
        transaction_type=item.transaction_type,
        debit_amount=item.debit_amount,
        credit_amount=item.credit_amount,
        annotation_types=item.annotation_types,
        annotation_notes=item.annotation_notes,
        has_linked_annotation=item.has_linked_annotation,
        status=item.status,
        analysis_note=item.analysis_note,
        resolution_bucket=item.resolution_bucket,
        recommended_review_status=item.recommended_review_status,
        resolution_reason=item.resolution_reason,
        exact_matches=[_build_match_response(match) for match in item.exact_matches],
        suggested_matches=[_build_match_response(match) for match in item.suggested_matches],
        supporting_matches=[_build_match_response(match) for match in item.supporting_matches],
    )


def _build_flow_document_response(document) -> TransactionFlowDocumentResponse:
    return TransactionFlowDocumentResponse(
        document_id=document.document_id,
        supplier=document.supplier,
        document_type=document.document_type,
        reference=document.reference,
        document_date=document.document_date,
        amount=document.amount,
        vat_amount=document.vat_amount,
        score=document.score,
        role=document.role,
        reason=document.reason,
        statement_kind=document.statement_kind,
        is_financial=document.is_financial,
        invoice_reference_count=document.invoice_reference_count,
        payment_reference_count=document.payment_reference_count,
        credit_reference_count=document.credit_reference_count,
        settlement_count=document.settlement_count,
    )


def _build_flow_response(flow) -> TransactionFlowResponse:
    def _ledger_entry_response(entry):
        return {
            "document_id": entry.document_id,
            "document_type": entry.document_type,
            "supplier": entry.supplier,
            "entry_kind": entry.entry_kind,
            "event_date": entry.event_date,
            "due_date": entry.due_date,
            "reference": entry.reference,
            "related_reference": entry.related_reference,
            "amount": entry.amount,
            "signed_amount": entry.signed_amount,
            "vat_amount": entry.vat_amount,
            "currency": entry.currency,
            "is_financial": entry.is_financial,
            "statement_kind": entry.statement_kind,
            "account_number": entry.account_number,
            "account_name": entry.account_name,
            "raw_text": entry.raw_text,
        }

    return TransactionFlowResponse(
        flow_type=flow.flow_type,
        supplier_label=flow.supplier_label,
        bank_counterparty=flow.bank_counterparty,
        next_step=flow.next_step,
        stages=[
            TransactionFlowStageResponse(
                key=stage.key,
                title=stage.title,
                status=stage.status,
                summary=stage.summary,
                items=list(stage.items),
                documents=[_build_flow_document_response(document) for document in stage.documents],
            )
            for stage in flow.stages
        ],
        settlements=[
            TransactionFlowSettlementResponse(
                source_document_id=settlement.source_document_id,
                source_supplier=settlement.source_supplier,
                source_reference=settlement.source_reference,
                source_document_date=settlement.source_document_date,
                statement_kind=settlement.statement_kind,
                payment_entry=_ledger_entry_response(settlement.payment_entry),
                component_entries=[
                    _ledger_entry_response(entry)
                    for entry in settlement.component_entries
                ],
                net_amount=settlement.net_amount,
                matches_transaction_amount=settlement.matches_transaction_amount,
            )
            for settlement in flow.settlements
            if settlement.payment_entry is not None
        ],
    )


def _build_transaction_link_response(link: TransactionDocumentLink) -> TransactionLinkResponse:
    if link.document is None:
        raise ValueError("Transaction link is missing its document relationship")
    return TransactionLinkResponse(
        id=link.id,
        transaction_id=link.transaction_id,
        document_id=link.document_id,
        role=link.role,
        status=link.status,
        score=link.score,
        confidence=link.confidence,
        match_reason=link.match_reason,
        amount_applied=link.amount_applied,
        note=link.note,
        created_at=link.created_at,
        updated_at=link.updated_at,
        document=TransactionLinkedDocumentResponse(
            id=link.document.id,
            supplier=link.document.supplier,
            document_type=link.document.document_type,
            reference=link.document.reference,
            document_date=link.document.document_date,
            amount=link.document.amount,
            vat_amount=link.document.vat_amount,
            local_path=link.document.local_path,
            needs_review=link.document.needs_review,
        ),
    )


async def _load_transaction_history(
    *,
    db: AsyncSession,
    user_id,
    transaction_id: uuid.UUID,
) -> list[TransactionReviewEvent]:
    result = await db.execute(
        select(TransactionReviewEvent)
        .where(
            TransactionReviewEvent.transaction_id == transaction_id,
            TransactionReviewEvent.user_id == user_id,
        )
        .order_by(TransactionReviewEvent.created_at.desc())
    )
    return list(result.scalars().all())


async def _build_transaction_detail_response(
    *,
    db: AsyncSession,
    user: User,
    transaction: Transaction,
    persist_exact_matches: bool,
) -> TransactionDetailResponse:
    candidate_documents = await load_candidate_documents_for_transaction(
        db=db,
        user_id=user.id,
        transaction=transaction,
    )
    supporting_documents = await load_supporting_documents_for_transaction(
        db=db,
        user_id=user.id,
        transaction=transaction,
    )
    candidate_ledgers = build_document_ledgers(candidate_documents)
    supporting_ledgers = build_document_ledgers(supporting_documents)
    analysis = build_transaction_reconciliation_item(
        transaction=transaction,
        documents=candidate_documents,
        supporting_documents=supporting_documents,
        document_ledgers=candidate_ledgers,
        supporting_document_ledgers=supporting_ledgers,
    )

    if persist_exact_matches and analysis.exact_matches:
        await sync_exact_transaction_document_links(
            db=db,
            user_id=user.id,
            exact_matches_by_transaction={transaction.id: analysis.exact_matches},
        )
        await db.commit()

    link_result = await db.execute(
        select(TransactionDocumentLink)
        .options(selectinload(TransactionDocumentLink.document))
        .where(
            TransactionDocumentLink.transaction_id == transaction.id,
            TransactionDocumentLink.user_id == user.id,
        )
        .order_by(TransactionDocumentLink.status.asc(), TransactionDocumentLink.created_at.asc())
    )
    persisted_links = list(link_result.scalars().all())
    flow = build_transaction_reconciliation_flow(
        transaction=transaction,
        analysis=analysis,
        invoice_documents=candidate_documents,
        supporting_documents=supporting_documents,
        invoice_ledgers=candidate_ledgers,
        supporting_ledgers=supporting_ledgers,
        persisted_links=persisted_links,
    )
    history_count = await db.scalar(
        select(func.count(TransactionReviewEvent.id)).where(
            TransactionReviewEvent.transaction_id == transaction.id,
            TransactionReviewEvent.user_id == user.id,
        )
    )

    return TransactionDetailResponse(
        transaction=_build_transaction_response(transaction),
        status=analysis.status,
        analysis_note=analysis.analysis_note,
        resolution_bucket=analysis.resolution_bucket,
        recommended_review_status=analysis.recommended_review_status,
        resolution_reason=analysis.resolution_reason,
        reconciliation_flow=_build_flow_response(flow),
        history_count=history_count or 0,
        persisted_links=[_build_transaction_link_response(link) for link in persisted_links],
        exact_matches=[_build_match_response(match) for match in analysis.exact_matches],
        suggested_matches=[_build_match_response(match) for match in analysis.suggested_matches],
        supporting_matches=[_build_match_response(match) for match in analysis.supporting_matches],
    )


async def _load_persisted_links_by_transaction(
    *,
    db: AsyncSession,
    user_id,
    transaction_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[TransactionDocumentLink]]:
    if not transaction_ids:
        return {}

    link_result = await db.execute(
        select(TransactionDocumentLink)
        .options(selectinload(TransactionDocumentLink.document))
        .where(
            TransactionDocumentLink.transaction_id.in_(transaction_ids),
            TransactionDocumentLink.user_id == user_id,
        )
        .order_by(
            TransactionDocumentLink.transaction_id.asc(),
            TransactionDocumentLink.status.asc(),
            TransactionDocumentLink.created_at.asc(),
        )
    )
    links = list(link_result.scalars().all())
    grouped: dict[uuid.UUID, list[TransactionDocumentLink]] = {}
    for link in links:
        grouped.setdefault(link.transaction_id, []).append(link)
    return grouped


@router.post("/import", response_model=TransactionImportResponse)
async def import_transactions(
    body: TransactionImportRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = body or TransactionImportRequest()
    try:
        if body.source_type == "vatbook":
            result = await import_transactions_from_vatbook(
                db=db,
                user_id=user.id,
                workbook_path=body.workbook_path,
                sheet_name=body.sheet_name,
                replace_existing=body.replace_existing,
            )
            response = TransactionImportResponse(
                source_type="vatbook",
                source_file=result.workbook_path,
                source_name=result.sheet_name,
                workbook_path=result.workbook_path,
                sheet_name=result.sheet_name,
                imported_transactions=result.imported_transactions,
                replaced_transactions=result.replaced_transactions,
                skipped_transactions=result.skipped_transactions,
                annotation_count=result.annotation_count,
                first_transaction_date=result.first_transaction_date,
                last_transaction_date=result.last_transaction_date,
                pubs=result.pubs,
            )
        else:
            from app.services.bank_statement_import import import_transactions_from_bank_statement

            result = await import_transactions_from_bank_statement(
                db=db,
                user_id=user.id,
                statement_path=body.statement_path,
                replace_existing=body.replace_existing,
            )
            response = TransactionImportResponse(
                source_type="bank_statement",
                source_file=result.statement_path,
                source_name=result.account_name,
                statement_path=result.statement_path,
                sheet_name=result.account_number,
                account_name=result.account_name,
                account_number=result.account_number,
                provider=result.provider,
                imported_transactions=result.imported_transactions,
                replaced_transactions=result.replaced_transactions,
                skipped_transactions=result.skipped_transactions,
                annotation_count=result.annotation_count,
                first_transaction_date=result.first_transaction_date,
                last_transaction_date=result.last_transaction_date,
                pubs=result.pubs,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()
    return response


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    month: str | None = None,
    source_type: str | None = None,
    pub: str | None = None,
    annotated_only: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    normalized_source_type = _parse_source_type(source_type)
    query = select(Transaction).where(Transaction.user_id == user.id)
    if normalized_source_type:
        query = query.where(Transaction.source_type == normalized_source_type)

    if month:
        start, end = _parse_month(month)
        query = query.where(Transaction.transaction_date >= start, Transaction.transaction_date < end)

    if pub:
        query = query.where(Transaction.pub == pub)

    result = await db.execute(query.order_by(Transaction.transaction_date.asc(), Transaction.row_number.asc()))
    transactions = list(result.scalars().all())

    if annotated_only:
        transactions = [transaction for transaction in transactions if transaction.annotation_notes]

    total = len(transactions)
    start_index = (page - 1) * limit
    page_items = transactions[start_index:start_index + limit]

    return TransactionListResponse(
        transactions=[_build_transaction_response(transaction) for transaction in page_items],
        total=total,
        page=page,
        pages=math.ceil(total / limit) if total else 1,
    )


@router.get("/review-queue", response_model=TransactionReviewQueueResponse)
async def get_transaction_review_queue(
    month: str,
    source_type: str | None = None,
    pub: str | None = None,
    status: str | None = None,
    resolution_bucket: str | None = None,
    review_status: str | None = None,
    annotated_only: bool | None = None,
    persist_exact_matches: bool = True,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _parse_month(month)
    normalized_source_type = _parse_source_type(source_type)
    effective_annotated_only = (
        annotated_only
        if annotated_only is not None
        else normalized_source_type != "bank_statement"
    )
    requested_statuses = None
    if status:
        requested_statuses = [value.strip() for value in status.split(",") if value.strip()]
    requested_resolution_buckets = _parse_resolution_buckets(resolution_bucket)
    requested_review_statuses = _parse_review_statuses(review_status)

    queue = await build_transaction_review_queue(
        db=db,
        user_id=user.id,
        month=month,
        source_type=normalized_source_type,
        pub=pub,
        statuses=requested_statuses,
        resolution_buckets=requested_resolution_buckets,
        review_statuses=requested_review_statuses,
        annotated_only=effective_annotated_only,
        persist_exact_matches=persist_exact_matches,
        page=page,
        limit=limit,
    )
    if persist_exact_matches:
        await db.commit()

    transaction_map = {
        item.transaction_id: item
        for item in queue.transactions
    }
    transaction_result = await db.execute(
        select(Transaction).where(Transaction.id.in_(list(transaction_map)))
    )
    transactions_by_id = {
        transaction.id: transaction
        for transaction in transaction_result.scalars().all()
    }
    links_by_transaction = await _load_persisted_links_by_transaction(
        db=db,
        user_id=user.id,
        transaction_ids=list(transaction_map),
    )

    items = []
    for item in queue.transactions:
        transaction = transactions_by_id[item.transaction_id]
        persisted_links = links_by_transaction.get(item.transaction_id, [])
        items.append(
            TransactionReviewQueueItemResponse(
                transaction=_build_transaction_response(transaction),
                status=item.status,
                needs_action=(
                    item.status != "matched"
                    and transaction.review_status not in RESOLVED_TRANSACTION_REVIEW_STATUSES
                ),
                analysis_note=item.analysis_note,
                resolution_bucket=item.resolution_bucket,
                recommended_review_status=item.recommended_review_status,
                resolution_reason=item.resolution_reason,
                persisted_links=[_build_transaction_link_response(link) for link in persisted_links],
                exact_matches=[_build_match_response(match) for match in item.exact_matches],
                suggested_matches=[_build_match_response(match) for match in item.suggested_matches],
                supporting_matches=[_build_match_response(match) for match in item.supporting_matches],
            )
        )

    return TransactionReviewQueueResponse(
        month=queue.month,
        pub=queue.pub,
        annotated_only=queue.annotated_only,
        statuses=queue.statuses,
        total=queue.total,
        page=queue.page,
        pages=queue.pages,
        matched_transactions=queue.matched_transactions,
        partial_transactions=queue.partial_transactions,
        suggested_transactions=queue.suggested_transactions,
        unmatched_transactions=queue.unmatched_transactions,
        resolution_bucket_counts=queue.resolution_bucket_counts,
        transactions=items,
    )


@router.get("/{transaction_id}/detail", response_model=TransactionDetailResponse)
async def get_transaction_detail(
    transaction_id: uuid.UUID,
    persist_exact_matches: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    transaction_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    transaction = transaction_result.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return await _build_transaction_detail_response(
        db=db,
        user=user,
        transaction=transaction,
        persist_exact_matches=persist_exact_matches,
    )


@router.get("/{transaction_id}/history", response_model=TransactionHistoryResponse)
async def get_transaction_history(
    transaction_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    transaction_result = await db.execute(
        select(Transaction.id).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    if transaction_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    events = await _load_transaction_history(db=db, user_id=user.id, transaction_id=transaction_id)
    return TransactionHistoryResponse(
        transaction_id=transaction_id,
        events=[_build_transaction_review_event_response(event) for event in events],
    )


@router.get("/{transaction_id}/links", response_model=TransactionLinksResponse)
async def get_transaction_links(
    transaction_id: uuid.UUID,
    persist_exact_matches: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    transaction_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    transaction = transaction_result.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    detail = await _build_transaction_detail_response(
        db=db,
        user=user,
        transaction=transaction,
        persist_exact_matches=persist_exact_matches,
    )

    return TransactionLinksResponse(
        transaction=detail.transaction,
        status=detail.status,
        analysis_note=detail.analysis_note,
        resolution_bucket=detail.resolution_bucket,
        recommended_review_status=detail.recommended_review_status,
        resolution_reason=detail.resolution_reason,
        persisted_links=detail.persisted_links,
        exact_matches=detail.exact_matches,
        suggested_matches=detail.suggested_matches,
        supporting_matches=detail.supporting_matches,
    )


@router.patch("/{transaction_id}/review", response_model=TransactionResponse)
async def update_transaction_review(
    transaction_id: uuid.UUID,
    body: TransactionReviewUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    transaction_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    transaction = transaction_result.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    previous_review_status = transaction.review_status
    previous_review_note = transaction.review_note
    previous_expected_supplier = transaction.expected_supplier
    transaction.review_status = body.review_status
    transaction.review_note = body.review_note
    transaction.expected_supplier = (body.expected_supplier or "").strip() or None
    transaction.reviewed_at = datetime.utcnow()
    _append_transaction_review_event(
        db=db,
        transaction=transaction,
        user=user,
        event_type="review_updated",
        previous_review_status=previous_review_status,
        current_review_status=transaction.review_status,
        payload={
            "previous_review_note": previous_review_note,
            "current_review_note": transaction.review_note,
            "previous_expected_supplier": previous_expected_supplier,
            "current_expected_supplier": transaction.expected_supplier,
        },
    )

    await db.commit()
    await db.refresh(transaction)
    return _build_transaction_response(transaction)


@router.post("/{transaction_id}/links", response_model=TransactionLinkResponse)
async def create_transaction_link(
    transaction_id: uuid.UUID,
    body: TransactionLinkCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    transaction_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    transaction = transaction_result.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    document_result = await db.execute(
        select(Document).where(Document.id == body.document_id, Document.user_id == user.id)
    )
    document = document_result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    link_result = await db.execute(
        select(TransactionDocumentLink)
        .options(selectinload(TransactionDocumentLink.document))
        .where(
            TransactionDocumentLink.transaction_id == transaction.id,
            TransactionDocumentLink.document_id == document.id,
            TransactionDocumentLink.role == body.role,
            TransactionDocumentLink.user_id == user.id,
        )
    )
    link = link_result.scalar_one_or_none()
    existing_link = link is not None
    if link is None:
        link = TransactionDocumentLink(
            user_id=user.id,
            transaction_id=transaction.id,
            document_id=document.id,
            role=body.role,
        )
        db.add(link)

    link.status = body.status
    link.score = body.score
    link.confidence = body.confidence
    link.match_reason = body.match_reason
    link.amount_applied = body.amount_applied
    link.note = body.note
    await _synchronize_transaction_review_state_for_link(
        db=db,
        transaction=transaction,
        document=document,
        link_status=link.status,
        user=user,
        link=link,
    )
    _append_transaction_review_event(
        db=db,
        transaction=transaction,
        user=user,
        event_type="link_updated" if existing_link else "link_created",
        previous_review_status=None,
        current_review_status=transaction.review_status,
        document_id=document.id,
        link_id=link.id,
        payload={
            "role": link.role,
            "link_status": link.status,
            "score": link.score,
            "confidence": link.confidence,
            "amount_applied": str(link.amount_applied) if isinstance(link.amount_applied, Decimal) else None,
            "note": link.note,
        },
    )

    await db.commit()
    await db.refresh(link, attribute_names=["document"])
    return _build_transaction_link_response(link)


@router.patch("/links/{link_id}", response_model=TransactionLinkResponse)
async def update_transaction_link(
    link_id: uuid.UUID,
    body: TransactionLinkUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    link_result = await db.execute(
        select(TransactionDocumentLink)
        .options(selectinload(TransactionDocumentLink.document))
        .where(TransactionDocumentLink.id == link_id, TransactionDocumentLink.user_id == user.id)
    )
    link = link_result.scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Transaction link not found")

    transaction_result = await db.execute(
        select(Transaction).where(
            Transaction.id == link.transaction_id,
            Transaction.user_id == user.id,
        )
    )
    transaction = transaction_result.scalar_one()

    previous_link_state = {
        "role": link.role,
        "status": link.status,
        "score": link.score,
        "confidence": link.confidence,
        "amount_applied": str(link.amount_applied) if isinstance(link.amount_applied, Decimal) else None,
        "note": link.note,
    }
    previous_review_status = transaction.review_status
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(link, field, value)

    if link.document is None:
        raise ValueError("Transaction link is missing its document relationship")
    await _synchronize_transaction_review_state_for_link(
        db=db,
        transaction=transaction,
        document=link.document,
        link_status=link.status,
        user=user,
        link=link,
    )
    _append_transaction_review_event(
        db=db,
        transaction=transaction,
        user=user,
        event_type="link_updated",
        previous_review_status=previous_review_status,
        current_review_status=transaction.review_status,
        document_id=link.document_id,
        link_id=link.id,
        payload={
            "previous_link_state": previous_link_state,
            "current_link_state": {
                "role": link.role,
                "status": link.status,
                "score": link.score,
                "confidence": link.confidence,
                "amount_applied": str(link.amount_applied) if isinstance(link.amount_applied, Decimal) else None,
                "note": link.note,
            },
        },
    )

    await db.commit()
    await db.refresh(link, attribute_names=["document"])
    return _build_transaction_link_response(link)


@router.get("/reconciliation-report", response_model=TransactionReconciliationReportResponse)
async def get_reconciliation_report(
    month: str,
    source_type: str | None = None,
    pub: str | None = None,
    annotated_only: bool | None = None,
    persist_exact_matches: bool = True,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _parse_month(month)
    normalized_source_type = _parse_source_type(source_type)
    effective_annotated_only = (
        annotated_only
        if annotated_only is not None
        else normalized_source_type != "bank_statement"
    )
    report = await build_reconciliation_report(
        db=db,
        user_id=user.id,
        month=month,
        source_type=normalized_source_type,
        pub=pub,
        limit=limit,
        annotated_only=effective_annotated_only,
        persist_exact_matches=persist_exact_matches,
    )
    if persist_exact_matches:
        await db.commit()

    return TransactionReconciliationReportResponse(
        month=report.month,
        pub=report.pub,
        total_transactions=report.total_transactions,
        expense_transactions=report.expense_transactions,
        annotated_transactions=report.annotated_transactions,
        linked_transactions=report.linked_transactions,
        matched_transactions=report.matched_transactions,
        partial_transactions=report.partial_transactions,
        suggested_transactions=report.suggested_transactions,
        unmatched_transactions=report.unmatched_transactions,
        invoice_documents_in_month=report.invoice_documents_in_month,
        unmatched_invoice_documents=report.unmatched_invoice_documents,
        resolution_bucket_counts=report.resolution_bucket_counts,
        transactions=[_build_reconciliation_item_response(item) for item in report.transactions],
        unmatched_documents=[_build_match_response(match) for match in report.unmatched_documents],
    )
