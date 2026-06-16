import uuid
import math
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import Document, GmailConnection, User
from app.schemas import (
    DocumentDetailResponse,
    DocumentDriveSyncRequest,
    DocumentDriveSyncResponse,
    DocumentStorageSyncRequest,
    DocumentStorageSyncResponse,
    DocumentExtractionCandidateResponse,
    DocumentLedgerAnalysisResponse,
    DocumentLedgerEntryResponse,
    DocumentLedgerSettlementResponse,
    DocumentStatementAnalysisResponse,
    DocumentStatementEntryResponse,
    DocumentExtractionRequest,
    DocumentExtractionResponse,
    DocumentFinancialBackfillRequest,
    DocumentFinancialBackfillResponse,
    LocalDocumentImportRequest,
    LocalDocumentImportResponse,
    StatementContextImportRequest,
    StatementContextImportResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentSplitResponse,
    DocumentUpdateRequest,
)
from app.services.document_candidates import extract_multi_invoice_candidates
from app.services.document_extraction import extract_documents
from app.services.document_financial_backfill import backfill_document_financial_state
from app.services.document_ledger import build_document_ledger, build_statement_settlements
from app.services.local_document_import import (
    import_documents_from_local_archive,
    import_statement_context_from_local_archive,
)
from app.services.object_storage import (
    ensure_local_document_file,
    object_storage_enabled,
    sync_documents_to_object_storage,
)
from app.services.document_relocation import refile_document_assets
from app.services.document_split import split_document_into_children, sync_child_documents_from_parent
from app.services.document_sync import sync_documents_to_drive
from app.services.invoice_projection import sync_invoices_from_documents
from app.services.supplier_statement_parser import parse_supplier_statement

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _build_document_response(document: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(document, from_attributes=True)


def _build_document_detail_response(
    document: Document,
    *,
    parent_document: Document | None = None,
    child_documents: list[Document] | None = None,
) -> DocumentDetailResponse:
    candidates = extract_multi_invoice_candidates(
        text=document.extracted_text or "",
        document_type=document.document_type,
        subject=document.source_email_subject or "",
    )
    parsed_statement = parse_supplier_statement(document)
    # Workbench detail view: previewing a not-yet-extracted statement via the
    # parser is intentional here; extracted documents use their persisted rows.
    ledger = build_document_ledger(document, allow_parse_fallback=True)
    base_payload = _build_document_response(document).model_dump()

    def _build_ledger_entry_response(entry) -> DocumentLedgerEntryResponse:
        return DocumentLedgerEntryResponse(
            document_id=entry.document_id,
            document_type=entry.document_type,
            supplier=entry.supplier,
            entry_kind=entry.entry_kind,
            event_date=entry.event_date,
            due_date=entry.due_date,
            reference=entry.reference,
            related_reference=entry.related_reference,
            amount=entry.amount,
            signed_amount=entry.signed_amount,
            vat_amount=entry.vat_amount,
            currency=entry.currency,
            is_financial=entry.is_financial,
            statement_kind=entry.statement_kind,
            account_number=entry.account_number,
            account_name=entry.account_name,
            raw_text=entry.raw_text,
        )

    return DocumentDetailResponse(
        **base_payload,
        extracted_text=document.extracted_text,
        extraction_candidates=[
            DocumentExtractionCandidateResponse.model_validate(candidate)
            for candidate in candidates
        ],
        statement_analysis=(
            DocumentStatementAnalysisResponse(
                statement_kind=parsed_statement.statement_kind,
                is_financial=parsed_statement.is_financial,
                account_number=parsed_statement.account_number,
                account_name=parsed_statement.account_name,
                period_start=parsed_statement.period_start,
                period_end=parsed_statement.period_end,
                total_due=parsed_statement.total_due,
                settlement_discount_total=parsed_statement.settlement_discount_total,
                closing_balance=parsed_statement.closing_balance,
                invoice_references=list(parsed_statement.invoice_references),
                payment_references=list(parsed_statement.payment_references),
                note=parsed_statement.note,
                entries=[
                    DocumentStatementEntryResponse(
                        event_date=entry.event_date,
                        reference=entry.reference,
                        transaction_type=entry.transaction_type,
                        due_date=entry.due_date,
                        clearing_reference=entry.clearing_reference,
                        amount=entry.amount,
                        raw_text=entry.raw_text,
                    )
                    for entry in parsed_statement.entries
                ],
            )
            if parsed_statement
            else None
        ),
        ledger_analysis=(
            DocumentLedgerAnalysisResponse(
                document_id=ledger.document_id,
                supplier=ledger.supplier,
                document_type=ledger.document_type,
                is_financial=ledger.is_financial,
                statement_kind=ledger.statement_kind,
                account_number=ledger.account_number,
                account_name=ledger.account_name,
                note=ledger.note,
                entries=[_build_ledger_entry_response(entry) for entry in ledger.entries],
                settlements=[
                    DocumentLedgerSettlementResponse(
                        payment_entry=_build_ledger_entry_response(settlement.payment_entry),
                        component_entries=[
                            _build_ledger_entry_response(component)
                            for component in settlement.component_entries
                        ],
                        net_amount=settlement.net_amount,
                    )
                    for settlement in build_statement_settlements(ledger)
                ],
            )
            if ledger
            else None
        ),
        parent_document=_build_document_response(parent_document) if parent_document else None,
        child_documents=[_build_document_response(child) for child in (child_documents or [])],
    )


@router.get("/store-summary")
async def get_document_store_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The document store as a tree, rendered from the DB (doc 29).

    Stage is derived, never stored, so it can't drift:
      captured        -> supplier still unknown ('Other')
      supplier_sorted -> supplier known, type still unknown
      extracted       -> typed + data pulled
    """
    result = await db.execute(
        select(Document).where(Document.user_id == user.id, Document.derivation_index == 0)
    )
    documents = list(result.scalars().all())

    def stage_of(d: Document) -> str:
        if not d.supplier or d.supplier == "Other":
            return "captured"
        if not d.document_type or d.document_type == "unknown":
            return "supplier_sorted"
        return "extracted"

    def in_r2(d: Document) -> bool:
        return d.storage_provider == "s3" and bool(d.storage_key)

    stages = {"captured": 0, "supplier_sorted": 0, "extracted": 0}
    storage = {"r2": 0, "local_only": 0}
    suppliers: dict[str, dict] = {}
    for d in documents:
        st = stage_of(d)
        stages[st] += 1
        storage["r2" if in_r2(d) else "local_only"] += 1
        key = d.supplier or "Other"
        s = suppliers.setdefault(
            key,
            {"supplier": key, "total": 0, "captured": 0, "supplier_sorted": 0, "extracted": 0, "types": {}, "in_r2": 0},
        )
        s["total"] += 1
        s[st] += 1
        if in_r2(d):
            s["in_r2"] += 1
        if st == "extracted":
            t = d.document_type or "unknown"
            s["types"][t] = s["types"].get(t, 0) + 1

    supplier_list = sorted(suppliers.values(), key=lambda x: (-x["total"], x["supplier"]))
    return {
        "total": len(documents),
        "stages": stages,
        "storage": storage,
        "suppliers": supplier_list,
    }


@router.get("/store-list")
async def get_document_store_list(
    supplier: str | None = None,
    document_type: str | None = None,
    unsorted: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the documents in one bucket of the store — the unsorted/captured
    pile, or a supplier optionally narrowed to one document type."""
    query = select(Document).where(Document.user_id == user.id, Document.derivation_index == 0)
    if unsorted:
        query = query.where(or_(Document.supplier.is_(None), Document.supplier == "Other"))
    elif supplier:
        query = query.where(Document.supplier == supplier)
        if document_type == "unknown":
            query = query.where(or_(Document.document_type.is_(None), Document.document_type == "unknown"))
        elif document_type:
            query = query.where(Document.document_type == document_type)
    else:
        raise HTTPException(status_code=422, detail="supplier or unsorted=true required")

    result = await db.execute(
        query.order_by(Document.document_date.desc().nulls_last(), Document.created_at.desc()).limit(500)
    )
    docs = list(result.scalars().all())
    return {
        "count": len(docs),
        "documents": [
            {
                "id": str(d.id),
                "attachment_name": d.attachment_name,
                "supplier": d.supplier,
                "document_type": d.document_type,
                "document_date": d.document_date.isoformat() if d.document_date else None,
                "amount": str(d.amount) if d.amount is not None else None,
                "in_r2": bool(d.storage_provider == "s3" and d.storage_key),
                "captured_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
    }


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    needs_review: bool | None = None,
    synced: bool | None = None,
    document_type: str | None = None,
    extraction_status: str | None = None,
    parent_document_id: uuid.UUID | None = None,
    include_split_containers: bool = False,
    min_confidence: float | None = Query(None, ge=0, le=1),
    max_confidence: float | None = Query(None, ge=0, le=1),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (
        min_confidence is not None
        and max_confidence is not None
        and min_confidence > max_confidence
    ):
        raise HTTPException(
            status_code=422,
            detail="min_confidence cannot be greater than max_confidence",
        )

    query = select(Document).where(Document.user_id == user.id)
    count_query = select(func.count(Document.id)).where(Document.user_id == user.id)

    if parent_document_id is not None:
        query = query.where(Document.parent_document_id == parent_document_id)
        count_query = count_query.where(Document.parent_document_id == parent_document_id)
    elif not include_split_containers:
        query = query.where(Document.extraction_status != "split")
        count_query = count_query.where(Document.extraction_status != "split")

    if needs_review is not None:
        query = query.where(Document.needs_review == needs_review)
        count_query = count_query.where(Document.needs_review == needs_review)

    if synced is True:
        query = query.where(Document.drive_file_id.is_not(None))
        count_query = count_query.where(Document.drive_file_id.is_not(None))
    elif synced is False:
        query = query.where(Document.drive_file_id.is_(None))
        count_query = count_query.where(Document.drive_file_id.is_(None))

    if document_type:
        query = query.where(Document.document_type == document_type)
        count_query = count_query.where(Document.document_type == document_type)

    if extraction_status:
        query = query.where(Document.extraction_status == extraction_status)
        count_query = count_query.where(Document.extraction_status == extraction_status)

    if min_confidence is not None:
        query = query.where(Document.confidence_score.is_not(None))
        query = query.where(Document.confidence_score >= min_confidence)
        count_query = count_query.where(Document.confidence_score.is_not(None))
        count_query = count_query.where(Document.confidence_score >= min_confidence)

    if max_confidence is not None:
        query = query.where(Document.confidence_score.is_not(None))
        query = query.where(Document.confidence_score <= max_confidence)
        count_query = count_query.where(Document.confidence_score.is_not(None))
        count_query = count_query.where(Document.confidence_score <= max_confidence)

    total = (await db.execute(count_query)).scalar() or 0
    order_by = [Document.created_at.desc()]
    if parent_document_id is not None:
        order_by = [
            Document.document_date.asc().nulls_last(),
            Document.derivation_index.asc(),
            Document.created_at.asc(),
        ]
    elif extraction_status == "review" or min_confidence is not None or max_confidence is not None:
        order_by = [Document.confidence_score.asc().nulls_last(), Document.created_at.desc()]

    query = query.order_by(*order_by).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[_build_document_response(document) for document in documents],
        total=total,
        page=page,
        pages=math.ceil(total / limit) if total else 1,
    )


@router.get("/review", response_model=DocumentListResponse)
async def list_review_documents(
    confidence_below: float = Query(0.7, ge=0, le=1),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review_condition = or_(
        Document.needs_review.is_(True),
        Document.extraction_status == "review",
        and_(
            Document.extraction_status.not_in(["reviewed", "split"]),
            Document.confidence_score.is_not(None),
            Document.confidence_score < confidence_below,
        ),
    )

    query = select(Document).where(
        Document.user_id == user.id,
        Document.extraction_status != "split",
        review_condition,
    )
    count_query = select(func.count(Document.id)).where(
        Document.user_id == user.id,
        Document.extraction_status != "split",
        review_condition,
    )

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(
        Document.needs_review.desc(),
        case((Document.extraction_status == "review", 0), else_=1),
        Document.confidence_score.asc().nulls_last(),
        Document.created_at.desc(),
    ).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[_build_document_response(document) for document in documents],
        total=total,
        page=page,
        pages=math.ceil(total / limit) if total else 1,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.financial_fact), selectinload(Document.financial_rows))
        .where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    parent_document = None
    child_documents: list[Document] = []

    if document.parent_document_id is not None:
        parent_result = await db.execute(
            select(Document).where(Document.id == document.parent_document_id, Document.user_id == user.id)
        )
        parent_document = parent_result.scalar_one_or_none()
    else:
        child_result = await db.execute(
            select(Document)
            .where(Document.parent_document_id == document.id, Document.user_id == user.id)
            .order_by(Document.derivation_index.asc(), Document.created_at.asc())
        )
        child_documents = list(child_result.scalars().all())

    return _build_document_detail_response(
        document,
        parent_document=parent_document,
        child_documents=child_documents,
    )


@router.get("/{document_id}/file", include_in_schema=False)
async def get_document_file(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        file_path = ensure_local_document_file(document)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"
    return FileResponse(file_path, media_type=media_type, filename=document.attachment_name)


@router.patch("/{document_id}", response_model=DocumentDetailResponse)
async def update_document(
    document_id: uuid.UUID,
    body: DocumentUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    connection = None
    if document.drive_file_id:
        connection_result = await db.execute(
            select(GmailConnection).where(
                GmailConnection.user_id == user.id,
                GmailConnection.is_active == True,
            )
        )
        connection = connection_result.scalar_one_or_none()

    updates = body.model_dump(exclude_unset=True)
    mark_reviewed = updates.pop("mark_reviewed", False)

    for field, value in updates.items():
        if field == "currency" and value is not None:
            value = value.upper()
        setattr(document, field, value)

    if mark_reviewed:
        document.needs_review = False
        document.review_reasons = []
        document.extraction_status = "reviewed"

    if document.parent_document_id is None:
        try:
            await refile_document_assets(document=document, connection=connection, db=db)
            await sync_child_documents_from_parent(parent_document=document, db=db)
        except FileNotFoundError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=502, detail=f"Failed to refile document: {exc.__class__.__name__}") from exc

    await sync_invoices_from_documents(
        db=db,
        user_id=user.id,
        document_ids=[document.id],
    )
    await db.commit()
    await db.refresh(document)
    return _build_document_detail_response(document)


@router.post("/{document_id}/approve", response_model=DocumentDetailResponse)
async def approve_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await update_document(
        document_id=document_id,
        body=DocumentUpdateRequest(mark_reviewed=True),
        user=user,
        db=db,
    )


@router.post("/{document_id}/split", response_model=DocumentSplitResponse)
async def split_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        summary = await split_document_into_children(document=document, db=db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    changed_document_ids = [document.id, *[child.id for child in summary["child_documents"]]]
    await sync_invoices_from_documents(
        db=db,
        user_id=user.id,
        document_ids=changed_document_ids,
    )
    await db.commit()
    await db.refresh(document)
    for child in summary["child_documents"]:
        await db.refresh(child)

    return DocumentSplitResponse(
        parent_document=_build_document_detail_response(document),
        child_documents=[_build_document_detail_response(child) for child in summary["child_documents"]],
        created=summary["created"],
        updated=summary["updated"],
        deleted=summary["deleted"],
    )


@router.post("/sync-drive", response_model=DocumentDriveSyncResponse)
async def sync_drive_documents(
    body: DocumentDriveSyncRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GmailConnection).where(
            GmailConnection.user_id == user.id,
            GmailConnection.is_active == True,
        )
    )
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=400, detail="Gmail is not connected")

    summary = await sync_documents_to_drive(
        user=user,
        connection=connection,
        db=db,
        limit=body.limit,
        document_ids=body.document_ids,
        force=body.force,
    )
    return DocumentDriveSyncResponse.model_validate(summary)


@router.post("/sync-storage", response_model=DocumentStorageSyncResponse)
async def sync_storage_documents(
    body: DocumentStorageSyncRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not object_storage_enabled():
        raise HTTPException(
            status_code=400,
            detail="Object storage is not configured. Set document_storage_backend=s3 and the S3 env vars first.",
        )

    summary = await sync_documents_to_object_storage(
        user=user,
        db=db,
        limit=body.limit,
        document_ids=body.document_ids,
        force=body.force,
    )
    return DocumentStorageSyncResponse.model_validate(summary)


@router.post("/extract", response_model=DocumentExtractionResponse)
async def extract_document_data(
    body: DocumentExtractionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await extract_documents(
        user=user,
        db=db,
        limit=body.limit,
        document_ids=body.document_ids,
        force=body.force,
    )
    return DocumentExtractionResponse.model_validate(summary)


@router.post("/backfill-financial-state", response_model=DocumentFinancialBackfillResponse)
async def backfill_document_financial_data(
    body: DocumentFinancialBackfillRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await backfill_document_financial_state(
        user=user,
        db=db,
        limit=body.limit,
        document_ids=body.document_ids,
        force=body.force,
    )
    return DocumentFinancialBackfillResponse.model_validate(summary)


@router.post("/import-local", response_model=LocalDocumentImportResponse)
async def import_local_documents(
    body: LocalDocumentImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        summary = await import_documents_from_local_archive(
            user=user,
            db=db,
            source_path=body.source_path,
            limit=body.limit,
            supplier_filters=body.supplier_filters,
            document_types=body.document_types,
            pub_filters=body.pub_filters,
            month=body.month,
            include_archives=body.include_archives,
            recurse=body.recurse,
            extract_after_import=body.extract_after_import,
        )
    except FileNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return LocalDocumentImportResponse.model_validate(summary, from_attributes=True)


@router.post("/import-statement-context", response_model=StatementContextImportResponse)
async def import_statement_context_documents(
    body: StatementContextImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        summary = await import_statement_context_from_local_archive(
            user=user,
            db=db,
            source_path=body.source_path,
            month=body.month,
            source_type=body.source_type,
            pub=body.pub,
            supplier_filters=body.supplier_filters,
            adjacent_months=body.adjacent_months,
            limit=body.limit,
            recurse=body.recurse,
            extract_after_import=body.extract_after_import,
        )
    except FileNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StatementContextImportResponse.model_validate(summary, from_attributes=True)
