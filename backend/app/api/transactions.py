import math
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import Document, Transaction, TransactionDocumentLink, TransactionReviewEvent, TransactionRule, User
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
    TransactionRuleCreateRequest,
    TransactionRuleApplyRequest,
    TransactionRuleApplyResponse,
    TransactionRuleListResponse,
    TransactionRuleCreateResponse,
    TransactionRuleResponse,
    TransactionReviewEventResponse,
    TransactionReviewUpdateRequest,
    TransactionLinkUpdateRequest,
    TransactionListResponse,
    TransactionPrimarySuggestionResponse,
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
    parse_selected_months,
    sync_exact_transaction_document_links,
)
from app.services.document_ledger import build_document_ledgers
from app.services.reconciliation_suggestions import (
    apply_primary_suggestion_to_analysis,
    build_match_lists_from_persisted_suggestions,
    load_active_reconciliation_suggestions,
    select_primary_reconciliation_suggestion,
    sync_reconciliation_suggestions,
)
from app.services.transaction_rules import (
    RULE_MATCH_FIELD_COUNTERPARTY,
    RULE_REVIEW_STATUS_HANDLED,
    STANDARD_REVIEW_STATUS_CATEGORIES,
    VALID_DOCUMENT_EXPECTATIONS,
    VALID_RULE_REVIEW_STATUSES,
    apply_transaction_rule,
    copy_transaction_rule_fields,
    default_rule_preset,
    compact_rule_match_value,
    find_matching_transaction_rule,
    load_transaction_rules,
    matching_transaction_rules,
    normalize_transaction_category,
    standard_category_for_review_status,
)
from app.services.vatbook_import import import_transactions_from_vatbook

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
VALID_TRANSACTION_SOURCE_TYPES = {"vatbook", "bank_statement"}
VALID_TRANSACTION_REVIEW_STATUSES = {
    "pending",
    "linked",
    "supporting_docs_only",
    "hard_copy_available",
    "handled_by_rule",
    "awaiting_document",
    "no_document_expected",
}
RESOLVED_TRANSACTION_REVIEW_STATUSES = {
    "linked",
    "supporting_docs_only",
    "hard_copy_available",
    "handled_by_rule",
    "no_document_expected",
}

HARD_COPY_AVAILABLE_REASON = "A hard-copy supplier document is available for this row, even though no imported PDF is linked yet"


def _effective_review_outcome(
    *,
    review_status: str,
    category: str | None,
    review_note: str | None,
    recommended_review_status: str | None,
    resolution_reason: str | None,
) -> tuple[str | None, str | None]:
    if review_status == "hard_copy_available":
        return "hard_copy_available", HARD_COPY_AVAILABLE_REASON
    if review_status == RULE_REVIEW_STATUS_HANDLED:
        label = category or "saved rule"
        note_suffix = f" {review_note}" if review_note else ""
        return RULE_REVIEW_STATUS_HANDLED, f"A saved transaction rule classifies this row as {label}.{note_suffix}".strip()
    return recommended_review_status, resolution_reason


def _parse_month(month: str) -> tuple[date, date]:
    try:
        return month_bounds(month)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="month must be in YYYY-MM format")


def _parse_source_type(
    source_type: str | None,
    *,
    # Bank statements are the source of truth for transactions; the VAT book
    # is reference material and must be requested explicitly.
    default: str | None = "bank_statement",
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


def _build_transaction_rule_response(rule: TransactionRule) -> TransactionRuleResponse:
    return TransactionRuleResponse(
        id=rule.id,
        source_type=rule.source_type,
        pub=rule.pub,
        match_field=rule.match_field,
        match_value=rule.match_value,
        display_label=rule.display_label,
        category_override=rule.category_override,
        review_status=rule.review_status,
        expected_supplier=rule.expected_supplier,
        document_expectation=rule.document_expectation,
        owner_note=rule.owner_note,
        is_active=rule.is_active,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _build_transaction_rule_event_payload(rule: TransactionRule) -> dict:
    return {
        "rule_id": str(rule.id),
        "category_override": rule.category_override,
        "document_expectation": rule.document_expectation,
        "expected_supplier": rule.expected_supplier,
        "owner_note": rule.owner_note,
        "match_value": rule.match_value,
    }


def _ignored_document_ids(persisted_links: list[TransactionDocumentLink]) -> set[uuid.UUID]:
    return {
        link.document_id
        for link in persisted_links
        if link.role == "ignore" and link.status == "rejected"
    }


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


def _apply_standard_review_category(
    *,
    transaction: Transaction,
    review_status: str,
    explicit_category: str | None = None,
) -> None:
    normalized_category = normalize_transaction_category(explicit_category)
    if normalized_category is not None:
        transaction.category = normalized_category
        return

    standard_category = standard_category_for_review_status(review_status)
    if standard_category is not None:
        transaction.category = standard_category
        return

    if review_status in {"pending", "awaiting_document"} and transaction.category in STANDARD_REVIEW_STATUS_CATEGORIES.values():
        transaction.category = None


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
        _apply_standard_review_category(
            transaction=transaction,
            review_status=transaction.review_status,
        )
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
        _apply_standard_review_category(
            transaction=transaction,
            review_status=transaction.review_status,
        )
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
        storage_state=match.storage_state,
        storage_provider=match.storage_provider,
        storage_bucket=match.storage_bucket,
        storage_key=match.storage_key,
        drive_file_id=match.drive_file_id,
        drive_web_link=match.drive_web_link,
        score=match.score,
        reason=match.reason,
    )


def _build_primary_suggestion_response(primary) -> TransactionPrimarySuggestionResponse | None:
    if primary is None:
        return None
    return TransactionPrimarySuggestionResponse(
        suggestion_type=primary.suggestion_type,
        status=primary.status,
        verifier_status=primary.verifier_status,
        confidence_score=primary.confidence_score,
        reason_summary=primary.reason_summary,
        resolution_bucket=primary.resolution_bucket,
        recommended_review_status=primary.recommended_review_status,
        matcher_status=primary.matcher_status,
        item_count=primary.item_count,
        document_count=primary.document_count,
        verifier_reasons=primary.verifier_reasons,
    )


def _build_reconciliation_item_response(item, *, primary_suggestion=None) -> TransactionReconciliationItemResponse:
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
        primary_suggestion=_build_primary_suggestion_response(primary_suggestion),
        exact_matches=[_build_match_response(match) for match in item.exact_matches],
        suggested_matches=[_build_match_response(match) for match in item.suggested_matches],
        supporting_matches=[_build_match_response(match) for match in item.supporting_matches],
    )


def _resolve_match_lists(*, analysis, persisted_suggestions: list | None):
    if persisted_suggestions:
        return build_match_lists_from_persisted_suggestions(persisted_suggestions)
    return analysis.exact_matches, analysis.suggested_matches, analysis.supporting_matches


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
        storage_state=document.storage_state,
        storage_provider=document.storage_provider,
        storage_bucket=document.storage_bucket,
        storage_key=document.storage_key,
        drive_file_id=document.drive_file_id,
        drive_web_link=document.drive_web_link,
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
            storage_state=(
                "r2_and_drive"
                if link.document.storage_key and link.document.drive_file_id
                else "r2_only"
                if link.document.storage_key
                else "drive_only"
                if link.document.drive_file_id
                else "local_only"
            ),
            storage_provider=link.document.storage_provider,
            storage_bucket=link.document.storage_bucket,
            storage_key=link.document.storage_key,
            drive_file_id=link.document.drive_file_id,
            drive_web_link=link.document.drive_web_link,
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
    persist_suggestions: bool,
) -> TransactionDetailResponse:
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
    ignored_document_ids = _ignored_document_ids(persisted_links)

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
    if ignored_document_ids:
        candidate_documents = [
            document for document in candidate_documents if document.id not in ignored_document_ids
        ]
        supporting_documents = [
            document for document in supporting_documents if document.id not in ignored_document_ids
        ]
    candidate_ledgers = build_document_ledgers(candidate_documents)
    supporting_ledgers = build_document_ledgers(supporting_documents)
    analysis = build_transaction_reconciliation_item(
        transaction=transaction,
        documents=candidate_documents,
        supporting_documents=supporting_documents,
        document_ledgers=candidate_ledgers,
        supporting_document_ledgers=supporting_ledgers,
    )
    if persist_suggestions:
        await sync_reconciliation_suggestions(
            db=db,
            user_id=user.id,
            transaction=transaction,
            analysis=analysis,
            candidate_documents=candidate_documents,
            supporting_documents=supporting_documents,
            candidate_ledgers=candidate_ledgers,
            supporting_ledgers=supporting_ledgers,
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
    suggestion_map = await load_active_reconciliation_suggestions(
        db=db,
        user_id=user.id,
        transaction_ids=[transaction.id],
    )
    primary_suggestion = select_primary_reconciliation_suggestion(
        suggestion_map.get(transaction.id)
    )
    apply_primary_suggestion_to_analysis(
        analysis=analysis,
        primary=primary_suggestion,
    )
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
    effective_review_status, effective_resolution_reason = _effective_review_outcome(
        review_status=transaction.review_status,
        category=transaction.category,
        review_note=transaction.review_note,
        recommended_review_status=analysis.recommended_review_status,
        resolution_reason=analysis.resolution_reason,
    )
    exact_matches, suggested_matches, supporting_matches = _resolve_match_lists(
        analysis=analysis,
        persisted_suggestions=suggestion_map.get(transaction.id),
    )

    return TransactionDetailResponse(
        transaction=_build_transaction_response(transaction),
        status=analysis.status,
        analysis_note=analysis.analysis_note,
        resolution_bucket=analysis.resolution_bucket,
        recommended_review_status=effective_review_status,
        resolution_reason=effective_resolution_reason,
        primary_suggestion=_build_primary_suggestion_response(primary_suggestion),
        reconciliation_flow=_build_flow_response(flow),
        history_count=history_count or 0,
        persisted_links=[_build_transaction_link_response(link) for link in persisted_links],
        exact_matches=[_build_match_response(match) for match in exact_matches],
        suggested_matches=[_build_match_response(match) for match in suggested_matches],
        supporting_matches=[_build_match_response(match) for match in supporting_matches],
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


@router.post("/import-bank-csv")
async def import_bank_csv(
    files: list[UploadFile] = File(...),
    careys_only: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload one or more Bank of Ireland CSV exports. They are cumulative and
    overlapping, so transactions are deduped on content — re-uploading the same
    or overlapping files never double-counts. Defaults to Careys-only."""
    from app.services.boi_csv_import import ACCOUNT_PUB, import_boi_csv_files

    payloads: list[tuple[str, str]] = []
    for upload in files:
        raw = await upload.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        payloads.append((upload.filename or "upload.csv", text))

    only_accounts = (
        {acct for acct, pub in ACCOUNT_PUB.items() if pub == "Careys"}
        if careys_only
        else None
    )
    result = await import_boi_csv_files(
        db=db, user_id=user.id, files=payloads, only_accounts=only_accounts
    )
    await db.commit()
    return {
        "files": result.files,
        "imported": result.imported_transactions,
        "duplicates_skipped": result.duplicate_transactions,
        "by_pub": result.accounts,
        "first_transaction_date": (
            result.first_transaction_date.isoformat() if result.first_transaction_date else None
        ),
        "last_transaction_date": (
            result.last_transaction_date.isoformat() if result.last_transaction_date else None
        ),
    }


async def _build_period_vat_book(
    *, db: AsyncSession, user: User, month: str, pub: str | None, source_type: str
):
    """Shared generator: train rules, load the period's transactions + their
    matched documents, and build VAT-book rows. Used by both the JSON view and
    the Excel export."""
    from app.services.vat_categorisation import build_vat_book, learn_ruleset

    start, end = _parse_month(month)
    target_source = _parse_source_type(source_type)

    training_result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.category.is_not(None),
            (Transaction.source_type == "vatbook") | (Transaction.category_confirmed.is_(True)),
            ~((Transaction.transaction_date >= start) & (Transaction.transaction_date < end)),
        )
    )
    ruleset = learn_ruleset(list(training_result.scalars().all()))

    target_query = select(Transaction).where(
        Transaction.user_id == user.id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date < end,
    )
    if target_source:
        target_query = target_query.where(Transaction.source_type == target_source)
    if pub:
        target_query = target_query.where(Transaction.pub == pub)
    target_result = await db.execute(
        target_query.order_by(Transaction.transaction_date.asc(), Transaction.row_number.asc())
    )
    targets = list(target_result.scalars().all())

    supplier_by_transaction: dict = {}
    document_vat_by_transaction: dict = {}
    documents_by_transaction: dict = {}
    target_ids = [t.id for t in targets]
    if target_ids:
        link_result = await db.execute(
            select(TransactionDocumentLink, Document)
            .join(Document, Document.id == TransactionDocumentLink.document_id)
            .where(
                TransactionDocumentLink.user_id == user.id,
                TransactionDocumentLink.transaction_id.in_(target_ids),
                TransactionDocumentLink.role.in_(["invoice", "credit_note", "statement"]),
            )
            .order_by(TransactionDocumentLink.created_at.asc())
        )
        for link, document in link_result.all():
            confirmed = link.status == "confirmed"
            if document.supplier and (confirmed or link.transaction_id not in supplier_by_transaction):
                supplier_by_transaction[link.transaction_id] = document.supplier
            if document.amount is not None and document.vat_amount is not None and (
                confirmed or link.transaction_id not in document_vat_by_transaction
            ):
                document_vat_by_transaction[link.transaction_id] = (document.amount, document.vat_amount)
            docs = documents_by_transaction.setdefault(link.transaction_id, [])
            if not any(d["document_id"] == str(document.id) for d in docs):
                docs.append({
                    "document_id": str(document.id),
                    "type": document.document_type,
                    "supplier": document.supplier,
                    "reference": document.reference,
                    "confirmed": confirmed,
                })

    rows = build_vat_book(
        targets=targets,
        ruleset=ruleset,
        supplier_by_transaction=supplier_by_transaction,
        document_vat_by_transaction=document_vat_by_transaction,
    )
    return targets, rows, ruleset, target_source, documents_by_transaction


@router.get("/vat-book")
async def get_vat_book(
    month: str,
    pub: str | None = None,
    source_type: str = "bank_statement",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stage A: generate VAT-book rows for a period.

    Rules are learned from the operator's categorised history (vatbook rows)
    *outside* the selected month, so accuracy shown for a vatbook month is a
    genuine held-out measure. For source_type=bank_statement it is pure
    generation (no ground truth to compare).
    """
    _, rows, ruleset, target_source, documents_by_transaction = await _build_period_vat_book(
        db=db, user=user, month=month, pub=pub, source_type=source_type
    )
    scored = [r for r in rows if r.category_correct is not None]
    correct = sum(1 for r in scored if r.category_correct)
    unknown = sum(1 for r in rows if r.source == "unknown")

    return {
        "month": month,
        "pub": pub,
        "source_type": target_source or "all",
        "rule_categories": ruleset.category_count(),
        "total": len(rows),
        "scored": len(scored),
        "category_correct": correct,
        "category_accuracy": round(correct / len(scored), 3) if scored else None,
        "unknown": unknown,
        "rows": [
            {
                "transaction_id": str(r.transaction_id),
                "transaction_date": r.transaction_date.isoformat() if r.transaction_date else None,
                "pub": r.pub,
                "description": r.description,
                "debit_amount": str(r.debit_amount) if r.debit_amount is not None else None,
                "credit_amount": str(r.credit_amount) if r.credit_amount is not None else None,
                "predicted_category": r.predicted_category,
                "predicted_band": r.predicted_band,
                "predicted_band_label": r.predicted_band_label,
                "source": r.source,
                "band_source": r.band_source,
                "actual_category": r.actual_category,
                "category_correct": r.category_correct,
                "confirmed": r.confirmed,
                "documents": documents_by_transaction.get(r.transaction_id, []),
            }
            for r in rows
        ],
    }


@router.post("/rebuild-matching")
async def rebuild_matching(
    month: str,
    pub: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the matcher for a month and persist the suggestions/exact links.
    This is the 'Run matcher' action — safe to re-run any time."""
    _parse_month(month)
    report = await build_reconciliation_report(
        db=db,
        user_id=user.id,
        month=month,
        pub=pub,
        limit=2000,
        annotated_only=False,
        persist_exact_matches=True,
        persist_suggestions=True,
    )
    return {
        "month": month,
        "pub": pub,
        "expense_transactions": report.expense_transactions,
        "matched": report.matched_transactions,
        "partial": report.partial_transactions,
        "suggested": report.suggested_transactions,
        "unmatched": report.unmatched_transactions,
        "buckets": report.resolution_bucket_counts,
    }


@router.get("/vat-book/export")
async def export_vat_book(
    month: str,
    pub: str | None = None,
    source_type: str = "bank_statement",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stage D: download the period's VAT book as .xlsx in O'Farrell's format."""
    from app.services.vat_book_export import write_vat_book_xlsx

    targets, rows, _ruleset, _src, documents_by_transaction = await _build_period_vat_book(
        db=db, user=user, month=month, pub=pub, source_type=source_type
    )
    rows_by_id = {r.transaction_id: r for r in rows}
    period_label = month.replace("-", " ")
    content = write_vat_book_xlsx(
        targets=targets,
        rows_by_id=rows_by_id,
        documents_by_transaction=documents_by_transaction,
        period_label=period_label,
    )

    pub_part = f" - {pub}" if pub else ""
    filename = f"CAREYS BAR - VAT-CASH - {month}{pub_part}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/vat-book/confirm-all")
async def confirm_all_vat_guesses(
    month: str,
    pub: str | None = None,
    source_type: str = "bank_statement",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept every confident category guess for a period in one go — confirms
    rows that have a predicted category and aren't already confirmed."""
    from app.services.vat_categorisation import set_transaction_category

    targets, rows, _ruleset, _src, _docs = await _build_period_vat_book(
        db=db, user=user, month=month, pub=pub, source_type=source_type
    )
    targets_by_id = {t.id: t for t in targets}
    confirmed = 0
    for row in rows:
        if row.source == "unknown" or not row.predicted_category or row.confirmed:
            continue
        txn = targets_by_id.get(row.transaction_id)
        if txn is None:
            continue
        set_transaction_category(txn, category=row.predicted_category, band=row.predicted_band)
        confirmed += 1
    await db.commit()
    return {"month": month, "confirmed": confirmed}


@router.get("/vat-categories")
async def get_vat_categories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Distinct categories the operator has used, with each one's usual VAT band —
    powers the inline category picker."""
    from app.services.vat_categorisation import VAT_BANDS, band_label, learn_ruleset

    result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.category.is_not(None),
            (Transaction.source_type == "vatbook") | (Transaction.category_confirmed.is_(True)),
        )
    )
    ruleset = learn_ruleset(list(result.scalars().all()))
    categories = sorted(set(ruleset.by_description.values()) | set(ruleset.category_band.keys()))
    return {
        "bands": [{"key": key, "label": label} for key, label, _ in VAT_BANDS],
        "categories": [
            {
                "category": c,
                "default_band": ruleset.category_band.get(c),
                "default_band_label": band_label(ruleset.category_band.get(c)),
            }
            for c in categories
        ],
    }


@router.patch("/{transaction_id}/category")
async def set_transaction_category_endpoint(
    transaction_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist an operator category decision (and its VAT band). The decision
    sticks on the transaction and teaches future categorisation."""
    from app.services.vat_categorisation import BAND_KEYS, set_transaction_category

    category = (body.get("category") or "").strip()
    if not category:
        raise HTTPException(status_code=422, detail="category is required")
    band = body.get("band")
    if band is not None and band not in BAND_KEYS:
        raise HTTPException(status_code=422, detail=f"band must be one of {', '.join(BAND_KEYS)} or null")

    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    transaction = result.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    set_transaction_category(transaction, category=category, band=band)
    await db.commit()
    return {"transaction_id": str(transaction_id), "category": category, "band": band, "confirmed": True}


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
    months: str | None = None,
    source_type: str | None = None,
    pub: str | None = None,
    status: str | None = None,
    resolution_bucket: str | None = None,
    review_status: str | None = None,
    annotated_only: bool | None = None,
    persist_exact_matches: bool = True,
    persist_suggestions: bool = True,
    window_months: int = 0,
    include_all: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _parse_month(month)
    if window_months < 0 or window_months > 3:
        raise HTTPException(status_code=422, detail="window_months must be between 0 and 3")
    selected_months = parse_selected_months(months)
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
        selected_months=selected_months,
        source_type=normalized_source_type,
        pub=pub,
        statuses=requested_statuses,
        resolution_buckets=requested_resolution_buckets,
        review_statuses=requested_review_statuses,
        annotated_only=effective_annotated_only,
        persist_exact_matches=persist_exact_matches,
        persist_suggestions=persist_suggestions,
        window_months=window_months,
        include_all=include_all,
        page=page,
        limit=limit,
    )
    if persist_exact_matches or persist_suggestions:
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
    suggestions_by_transaction = await load_active_reconciliation_suggestions(
        db=db,
        user_id=user.id,
        transaction_ids=list(transaction_map),
    )

    items = []
    for item in queue.transactions:
        transaction = transactions_by_id[item.transaction_id]
        persisted_links = links_by_transaction.get(item.transaction_id, [])
        primary_suggestion = select_primary_reconciliation_suggestion(
            suggestions_by_transaction.get(item.transaction_id)
        )
        apply_primary_suggestion_to_analysis(
            analysis=item,
            primary=primary_suggestion,
        )
        exact_matches, suggested_matches, supporting_matches = _resolve_match_lists(
            analysis=item,
            persisted_suggestions=suggestions_by_transaction.get(item.transaction_id),
        )
        effective_review_status, effective_resolution_reason = _effective_review_outcome(
            review_status=transaction.review_status,
            category=transaction.category,
            review_note=transaction.review_note,
            recommended_review_status=item.recommended_review_status,
            resolution_reason=item.resolution_reason,
        )
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
                recommended_review_status=effective_review_status,
                resolution_reason=effective_resolution_reason,
                primary_suggestion=_build_primary_suggestion_response(primary_suggestion),
                persisted_links=[_build_transaction_link_response(link) for link in persisted_links],
                exact_matches=[_build_match_response(match) for match in exact_matches],
                suggested_matches=[_build_match_response(match) for match in suggested_matches],
                supporting_matches=[_build_match_response(match) for match in supporting_matches],
            )
        )

    response_status_counts = {
        "matched": 0,
        "partial": 0,
        "suggested": 0,
        "unmatched": 0,
    }
    response_bucket_counts: dict[str, int] = {}
    for item in items:
        response_status_counts[item.status] = response_status_counts.get(item.status, 0) + 1
        response_bucket_counts[item.resolution_bucket] = response_bucket_counts.get(item.resolution_bucket, 0) + 1

    return TransactionReviewQueueResponse(
        month=queue.month,
        selected_months=queue.selected_months,
        window_months=queue.window_months,
        pub=queue.pub,
        annotated_only=queue.annotated_only,
        statuses=queue.statuses,
        total=queue.total,
        page=queue.page,
        pages=queue.pages,
        matched_transactions=response_status_counts["matched"],
        partial_transactions=response_status_counts["partial"],
        suggested_transactions=response_status_counts["suggested"],
        unmatched_transactions=response_status_counts["unmatched"],
        resolution_bucket_counts=response_bucket_counts,
        transactions=items,
    )


@router.get("/rules", response_model=TransactionRuleListResponse)
async def list_transaction_rules(
    source_type: str | None = None,
    pub: str | None = None,
    transaction_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    normalized_source_type = _parse_source_type(source_type)
    rules = await load_transaction_rules(
        db=db,
        user_id=user.id,
        source_type=normalized_source_type,
    )
    if pub:
        rules = [rule for rule in rules if rule.pub is None or rule.pub == pub]
    if transaction_id is not None:
        transaction_result = await db.execute(
            select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
        )
        transaction = transaction_result.scalar_one_or_none()
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transaction not found")
        matching_rule_ids = {
            rule.id
            for rule in matching_transaction_rules(
                transaction=transaction,
                rules=rules,
            )
        }
        rules = sorted(
            rules,
            key=lambda rule: (
                0 if rule.id in matching_rule_ids else 1,
                0 if rule.pub == transaction.pub and transaction.pub else 1,
                0 if rule.display_label else 1,
            ),
        )
    return TransactionRuleListResponse(
        rules=[_build_transaction_rule_response(rule) for rule in rules]
    )


@router.get("/{transaction_id}/detail", response_model=TransactionDetailResponse)
async def get_transaction_detail(
    transaction_id: uuid.UUID,
    persist_exact_matches: bool = False,
    persist_suggestions: bool = True,
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
        persist_suggestions=persist_suggestions,
    )
    if persist_exact_matches or persist_suggestions:
        await db.commit()
    return detail


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
    persist_suggestions: bool = True,
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
        persist_suggestions=persist_suggestions,
    )
    if persist_exact_matches or persist_suggestions:
        await db.commit()

    return TransactionLinksResponse(
        transaction=detail.transaction,
        status=detail.status,
        analysis_note=detail.analysis_note,
        resolution_bucket=detail.resolution_bucket,
        recommended_review_status=detail.recommended_review_status,
        resolution_reason=detail.resolution_reason,
        primary_suggestion=detail.primary_suggestion,
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
    previous_category = transaction.category
    transaction.review_status = body.review_status
    _apply_standard_review_category(
        transaction=transaction,
        review_status=body.review_status,
        explicit_category=body.category,
    )
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
            "previous_category": previous_category,
            "current_category": transaction.category,
            "previous_review_note": previous_review_note,
            "current_review_note": transaction.review_note,
            "previous_expected_supplier": previous_expected_supplier,
            "current_expected_supplier": transaction.expected_supplier,
        },
    )

    await db.commit()
    await db.refresh(transaction)
    return _build_transaction_response(transaction)


@router.post("/{transaction_id}/apply-rule", response_model=TransactionRuleApplyResponse)
async def apply_existing_transaction_rule(
    transaction_id: uuid.UUID,
    body: TransactionRuleApplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    transaction_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    transaction = transaction_result.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    rule_result = await db.execute(
        select(TransactionRule).where(
            TransactionRule.id == body.rule_id,
            TransactionRule.user_id == user.id,
            TransactionRule.is_active.is_(True),
        )
    )
    rule = rule_result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Transaction rule not found")

    if rule.source_type != transaction.source_type:
        raise HTTPException(status_code=422, detail="Transaction rule source_type does not match this transaction")
    if rule.pub is not None and rule.pub != transaction.pub:
        raise HTTPException(status_code=422, detail="Transaction rule pub does not match this transaction")

    matching_rule = find_matching_transaction_rule(transaction=transaction, rules=[rule])
    applied_rule = matching_rule
    template_rule_id: uuid.UUID | None = None
    if applied_rule is None:
        match_value = compact_rule_match_value(transaction.source_type, transaction.description1)
        if not match_value:
            raise HTTPException(status_code=422, detail="This transaction does not have a reusable bank payee pattern")

        target_pub = rule.pub if rule.pub is None else transaction.pub
        applied_rule_result = await db.execute(
            select(TransactionRule).where(
                TransactionRule.user_id == user.id,
                TransactionRule.source_type == transaction.source_type,
                TransactionRule.pub == target_pub,
                TransactionRule.match_field == RULE_MATCH_FIELD_COUNTERPARTY,
                TransactionRule.match_value == match_value,
            )
        )
        applied_rule = applied_rule_result.scalar_one_or_none()
        if applied_rule is None:
            applied_rule = TransactionRule(
                user_id=user.id,
                source_type=transaction.source_type,
                pub=target_pub,
                match_field=RULE_MATCH_FIELD_COUNTERPARTY,
                match_value=match_value,
            )
            db.add(applied_rule)
        copy_transaction_rule_fields(
            source_rule=rule,
            target_rule=applied_rule,
            display_label=transaction.description1,
        )
        template_rule_id = rule.id

    previous_review_status = transaction.review_status
    applied = apply_transaction_rule(
        transaction=transaction,
        rule=applied_rule,
        force=True,
    )
    transaction.reviewed_at = datetime.utcnow()
    payload = _build_transaction_rule_event_payload(applied_rule)
    if template_rule_id is not None:
        payload["template_rule_id"] = str(template_rule_id)
    _append_transaction_review_event(
        db=db,
        transaction=transaction,
        user=user,
        event_type="rule_applied",
        previous_review_status=previous_review_status,
        current_review_status=transaction.review_status,
        payload=payload,
    )

    rule_scope_query = select(Transaction).where(
        Transaction.user_id == user.id,
        Transaction.source_type == transaction.source_type,
    )
    if applied_rule.pub is not None:
        rule_scope_query = rule_scope_query.where(Transaction.pub == applied_rule.pub)
    rule_scope_result = await db.execute(rule_scope_query)
    scoped_transactions = list(rule_scope_result.scalars().all())
    for scoped_transaction in scoped_transactions:
        if scoped_transaction.id == transaction.id:
            continue
        if compact_rule_match_value(scoped_transaction.source_type, scoped_transaction.description1) != applied_rule.match_value:
            continue
        scoped_previous_review_status = scoped_transaction.review_status
        scoped_applied = apply_transaction_rule(
            transaction=scoped_transaction,
            rule=applied_rule,
            force=False,
        )
        if scoped_applied is None:
            continue
        scoped_transaction.reviewed_at = datetime.utcnow()
        _append_transaction_review_event(
            db=db,
            transaction=scoped_transaction,
            user=user,
            event_type="rule_applied",
            previous_review_status=scoped_previous_review_status,
            current_review_status=scoped_transaction.review_status,
            payload=payload,
        )

    await db.commit()
    await db.refresh(transaction)
    await db.refresh(applied_rule)
    return TransactionRuleApplyResponse(
        transaction=_build_transaction_response(transaction),
        rule=_build_transaction_rule_response(applied_rule),
    )


@router.post("/{transaction_id}/rule", response_model=TransactionRuleCreateResponse)
async def create_transaction_rule(
    transaction_id: uuid.UUID,
    body: TransactionRuleCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    transaction_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    transaction = transaction_result.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if body.review_status not in VALID_RULE_REVIEW_STATUSES:
        allowed = ", ".join(sorted(VALID_RULE_REVIEW_STATUSES))
        raise HTTPException(status_code=422, detail=f"review_status must be one of: {allowed}")
    if body.document_expectation not in VALID_DOCUMENT_EXPECTATIONS:
        allowed = ", ".join(sorted(VALID_DOCUMENT_EXPECTATIONS))
        raise HTTPException(status_code=422, detail=f"document_expectation must be one of: {allowed}")

    match_value = compact_rule_match_value(transaction.source_type, transaction.description1)
    if not match_value:
        raise HTTPException(status_code=422, detail="This transaction does not have a reusable bank payee pattern")

    rule_query = select(TransactionRule).where(
        TransactionRule.user_id == user.id,
        TransactionRule.source_type == transaction.source_type,
        TransactionRule.pub == (transaction.pub if body.apply_same_pub_only else None),
        TransactionRule.match_field == RULE_MATCH_FIELD_COUNTERPARTY,
        TransactionRule.match_value == match_value,
    )
    rule_result = await db.execute(rule_query)
    rule = rule_result.scalar_one_or_none()

    if rule is None:
        rule = TransactionRule(
            user_id=user.id,
            source_type=transaction.source_type,
            pub=transaction.pub if body.apply_same_pub_only else None,
            match_field=RULE_MATCH_FIELD_COUNTERPARTY,
            match_value=match_value,
        )
        db.add(rule)

    category_override = normalize_transaction_category(body.category_override)
    category_preset = default_rule_preset(category_override)
    expected_supplier = (body.expected_supplier or "").strip() or None
    owner_note = (body.owner_note or "").strip() or None
    effective_review_status = body.review_status
    effective_document_expectation = body.document_expectation
    if category_preset:
        effective_review_status = category_preset["review_status"]
        effective_document_expectation = category_preset["document_expectation"]
        if owner_note is None:
            owner_note = category_preset["default_note"]

    template_rule = TransactionRule(
        source_type=transaction.source_type,
        pub=rule.pub,
        match_field=RULE_MATCH_FIELD_COUNTERPARTY,
        match_value=rule.match_value,
        display_label=transaction.description1,
        category_override=category_override,
        review_status=effective_review_status,
        expected_supplier=expected_supplier,
        document_expectation=effective_document_expectation,
        owner_note=owner_note,
        is_active=True,
    )
    copy_transaction_rule_fields(
        source_rule=template_rule,
        target_rule=rule,
        display_label=transaction.description1,
    )

    updated_transactions = 0
    if body.apply_to_existing:
        rule_scope_query = select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.source_type == transaction.source_type,
        )
        if rule.pub is not None:
            rule_scope_query = rule_scope_query.where(Transaction.pub == rule.pub)
        rule_scope_result = await db.execute(rule_scope_query)
        scoped_transactions = list(rule_scope_result.scalars().all())
    else:
        scoped_transactions = [transaction]

    for scoped_transaction in scoped_transactions:
        if compact_rule_match_value(scoped_transaction.source_type, scoped_transaction.description1) != match_value:
            continue
        previous_review_status = scoped_transaction.review_status
        applied = apply_transaction_rule(
            transaction=scoped_transaction,
            rule=rule,
            force=scoped_transaction.id == transaction.id,
        )
        if applied is None:
            continue
        scoped_transaction.reviewed_at = datetime.utcnow()
        updated_transactions += 1
        _append_transaction_review_event(
            db=db,
            transaction=scoped_transaction,
            user=user,
            event_type="rule_applied",
            previous_review_status=previous_review_status,
            current_review_status=scoped_transaction.review_status,
            payload=_build_transaction_rule_event_payload(rule),
        )

    await db.commit()
    await db.refresh(rule)
    await db.refresh(transaction)
    return TransactionRuleCreateResponse(
        transaction=_build_transaction_response(transaction),
        rule=_build_transaction_rule_response(rule),
        updated_transactions=updated_transactions,
    )


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
    persist_suggestions: bool = True,
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
        persist_suggestions=persist_suggestions,
    )
    if persist_exact_matches or persist_suggestions:
        await db.commit()
    suggestions_by_transaction = await load_active_reconciliation_suggestions(
        db=db,
        user_id=user.id,
        transaction_ids=[item.transaction_id for item in report.transactions],
    )
    response_transactions = []
    for item in report.transactions:
        primary_suggestion = select_primary_reconciliation_suggestion(
            suggestions_by_transaction.get(item.transaction_id)
        )
        apply_primary_suggestion_to_analysis(
            analysis=item,
            primary=primary_suggestion,
        )
        response_transactions.append(
            _build_reconciliation_item_response(
                item,
                primary_suggestion=primary_suggestion,
            )
        )

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
        transactions=response_transactions,
        unmatched_documents=[_build_match_response(match) for match in report.unmatched_documents],
    )
