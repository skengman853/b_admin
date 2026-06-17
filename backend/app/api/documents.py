import uuid
import math
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import Document, GmailConnection, ReconciliationSuggestion, User
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
from app.services.document_financial_state import _document_pub_hint
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


def _document_pub_label(d: Document) -> str:
    """Which pub a document belongs to, for the store tabs. Derived (never
    stored) from the same hints the financial layer uses; None -> 'Unknown'."""
    return _document_pub_hint(d) or "Unknown"


@router.get("/store-summary")
async def get_document_store_summary(
    pub: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The document store as a tree, rendered from the DB (doc 29).

    Stage is derived, never stored, so it can't drift:
      captured        -> supplier still unknown ('Other')
      supplier_sorted -> supplier known, type still unknown
      extracted       -> typed + data pulled

    Optionally narrowed to one pub (Careys / Canal / Unknown). Pub is derived
    per document; per-pub counts are always returned for the tab strip.
    """
    result = await db.execute(
        select(Document).where(Document.user_id == user.id, Document.derivation_index == 0)
    )
    all_documents = list(result.scalars().all())

    pubs: dict[str, int] = {}
    for d in all_documents:
        label = _document_pub_label(d)
        pubs[label] = pubs.get(label, 0) + 1

    if pub:
        documents = [d for d in all_documents if _document_pub_label(d) == pub]
    else:
        documents = all_documents

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
        "pubs": pubs,
        "pub": pub,
    }


@router.get("/store-list")
async def get_document_store_list(
    supplier: str | None = None,
    document_type: str | None = None,
    unsorted: bool = False,
    pub: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the documents in one bucket of the store — the unsorted/captured
    pile, or a supplier optionally narrowed to one document type. Optionally
    restricted to one pub (Careys / Canal / Unknown)."""
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
        query.order_by(Document.document_date.desc().nulls_last(), Document.created_at.desc())
    )
    docs = list(result.scalars().all())
    if pub:
        docs = [d for d in docs if _document_pub_label(d) == pub]
    docs = docs[:500]
    return {
        "count": len(docs),
        "documents": [
            {
                "id": str(d.id),
                "attachment_name": d.attachment_name,
                "supplier": d.supplier,
                "pub": _document_pub_label(d),
                "document_type": d.document_type,
                "document_date": d.document_date.isoformat() if d.document_date else None,
                "amount": str(d.amount) if d.amount is not None else None,
                "in_r2": bool(d.storage_provider == "s3" and d.storage_key),
                "captured_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
    }


def _document_source(d: Document) -> str:
    """How the document entered the system:
      drive   -> pulled from the client's Google Drive folders
      archive -> bulk-imported from a local archive folder on disk
      email   -> pulled from the Gmail inbox (real sender + received time)
    Drive and local-archive imports carry sentinel senders / id prefixes."""
    gid = d.gmail_message_id or ""
    sender = d.source_email_sender or ""
    if gid.startswith("drive-") or sender == "google-drive":
        return "drive"
    if gid.startswith("local-archive") or sender == "local-archive":
        return "archive"
    return "email"


@router.get("/inbox")
async def get_document_inbox(
    source: str = "all",
    pub: str | None = None,
    since_days: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Provenance view: which documents arrived how, and when. source tabs
    (email / drive / archive / all); since_days limits to what was imported in
    the last N days (0 = all time). Per-source counts reflect the time window."""
    from datetime import timedelta

    result = await db.execute(
        select(Document).where(Document.user_id == user.id, Document.derivation_index == 0)
    )
    all_docs = list(result.scalars().all())

    # Time window on import time (created_at) — "what did I import today / this week".
    if since_days and since_days > 0:
        cutoff = datetime.utcnow() - timedelta(days=since_days)
        all_docs = [d for d in all_docs if d.created_at and d.created_at >= cutoff]

    sources: dict[str, int] = {}
    for d in all_docs:
        s = _document_source(d)
        sources[s] = sources.get(s, 0) + 1

    docs = all_docs
    if source and source != "all":
        docs = [d for d in docs if _document_source(d) == source]
    if pub:
        docs = [d for d in docs if _document_pub_label(d) == pub]

    # Most recently imported first (this view is about "what came in when").
    docs.sort(key=lambda d: (d.created_at is not None, d.created_at), reverse=True)
    docs = docs[:500]

    return {
        "sources": sources,
        "source": source,
        "since_days": since_days,
        "window_total": len(all_docs),
        "count": len(docs),
        "documents": [
            {
                "id": str(d.id),
                "attachment_name": d.attachment_name,
                "supplier": d.supplier,
                "pub": _document_pub_label(d),
                "document_type": d.document_type,
                "document_date": d.document_date.isoformat() if d.document_date else None,
                "amount": str(d.amount) if d.amount is not None else None,
                "source": _document_source(d),
                "sender": d.source_email_sender if _document_source(d) in ("email", "drive") else None,
                "subject": d.source_email_subject if _document_source(d) in ("email", "drive") else None,
                "received_at": d.source_received_at.isoformat() if d.source_received_at else None,
                "imported_at": d.created_at.isoformat() if d.created_at else None,
                "in_r2": bool(d.storage_provider == "s3" and d.storage_key),
            }
            for d in docs
        ],
    }


@router.post("/wipe")
async def wipe_documents(
    confirm: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete ALL of this user's documents for a clean re-import. Cascades to
    extraction runs, financial facts/rows, invoices and transaction links.
    Bank transactions are NOT touched. Match suggestions are cleared too (you'll
    re-match). Requires confirm=true. The PDF bytes in R2 are left as orphans
    (harmless; re-import writes fresh copies)."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to wipe all documents.")

    doc_count = (
        await db.execute(select(func.count(Document.id)).where(Document.user_id == user.id))
    ).scalar() or 0
    # Suggestions reference transactions (not cascaded by document delete); clear
    # them so no stale matches remain. Items cascade from the suggestion.
    await db.execute(delete(ReconciliationSuggestion).where(ReconciliationSuggestion.user_id == user.id))
    # Documents cascade-delete their runs/facts/rows/invoices/links at the DB level.
    await db.execute(delete(Document).where(Document.user_id == user.id))
    await db.commit()
    return {"deleted_documents": doc_count}


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


@router.post("/extract-job")
async def start_extract_job(
    force: bool = False,
    year: int | None = None,
    month: int | None = None,
    user: User = Depends(get_current_user),
):
    """Kick off extraction on the background worker — processes pending
    documents server-side to completion (no request timeout, no babysitting).
    Optional year/month limits it to documents dated in that period.
    Returns a task id to poll via /api/documents/job/{task_id}."""
    from app.tasks.jobs import extract_documents_job

    task = extract_documents_job.delay(str(user.id), force, year, month)
    return {"task_id": task.id, "state": "queued"}


@router.get("/job/{task_id}")
async def get_job_status(
    task_id: str,
    user: User = Depends(get_current_user),
):
    """Poll a background job. Returns its state plus progress
    (extracted/skipped/done/total) while running, and the summary when done."""
    from app.tasks.celery_app import celery_app

    res = celery_app.AsyncResult(task_id)
    payload: dict = {"task_id": task_id, "state": res.state}
    info = res.info
    if res.state == "PROGRESS" and isinstance(info, dict):
        payload["progress"] = info
    elif res.state == "SUCCESS":
        payload["result"] = res.result
    elif res.state == "FAILURE":
        payload["error"] = str(info)[:300]
    return payload


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


@router.get("/drive-folders")
async def list_drive_folders(
    folder_id: str | None = None,
    folder_name: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Browse a Drive folder: list its subfolders and how many PDFs sit directly
    in it, so the operator can drill to the exact folder to import."""
    from sqlalchemy import select as _select

    from app.models import GmailConnection
    from app.services.drive_client import (
        find_folder_by_name,
        find_folder_by_path,
        get_drive_service,
        list_immediate_folders,
    )

    connection = (
        await db.execute(_select(GmailConnection).where(GmailConnection.user_id == user.id))
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=400, detail="Connect Google on the Tools page first.")
    service = await get_drive_service(connection, db)

    if not folder_id:
        if not folder_name:
            raise HTTPException(status_code=400, detail="Provide a Drive folder id, name or link.")
        folder = (
            find_folder_by_path(service, folder_name)
            if "/" in folder_name
            else find_folder_by_name(service, name=folder_name)
        )
        if folder is None:
            raise HTTPException(status_code=400, detail=f"No Drive folder found for {folder_name!r}.")
        folder_id = folder["id"]

    try:
        subfolders, direct_pdfs = list_immediate_folders(service, folder_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}"[:300]) from exc
    return {"folder_id": folder_id, "subfolders": subfolders, "direct_pdfs": direct_pdfs}


@router.post("/import-drive")
async def import_drive_documents(
    folder_name: str | None = None,
    folder_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    year: int | None = None,
    extract_after_import: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import documents from the client's Google Drive folders. Chunked (limit)
    and deduped on Drive file id, so call it repeatedly until nothing new is
    imported. Optional `year` skips files dated to other years. Needs the
    drive.readonly scope (reconnect Google if older)."""
    from app.services.drive_document_import import import_documents_from_drive

    try:
        result = await import_documents_from_drive(
            user=user,
            db=db,
            folder_name=folder_name,
            folder_id=folder_id,
            limit=limit,
            year=year,
            extract_after_import=extract_after_import,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface the real cause to the UI
        await db.rollback()
        detail = f"{type(exc).__name__}: {exc}"
        if "insufficientPermissions" in detail or "insufficient" in detail.lower() or "scope" in detail.lower():
            detail += " — reconnect Google on the Tools page and approve Drive access."
        raise HTTPException(status_code=502, detail=detail[:500]) from exc

    return {
        "folder": result.folder,
        "eligible_files": result.eligible_files,
        "already_imported": result.already_imported,
        "imported": result.imported_documents,
        "extracted": result.extracted_documents,
        "skipped_non_pdf": result.skipped_files,
        "skipped_other_year": result.filtered_year,
        "more_remaining": result.more_remaining,
        "errors": result.errors[:20],
    }


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
