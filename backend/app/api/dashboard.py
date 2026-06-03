from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import User, Invoice, Document
from app.schemas import (
    DashboardSummary,
    DocumentStorageSummaryResponse,
    SupplierDocumentInventoryItemResponse,
    SupplierDocumentInventoryResponse,
    SupplierOptionResponse,
    SupplierOptionsResponse,
)
from app.services.invoice_projection import sync_invoices_from_documents
from app.services.supplier_profiles import canonicalize_supplier_name, build_supplier_lookup_keys

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
