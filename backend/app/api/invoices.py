import math
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Document, User, Invoice
from app.schemas import InvoiceResponse, InvoiceListResponse, InvoiceUpdateRequest
from app.services.invoice_projection import sync_invoices_from_documents

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    status: str | None = None,
    month: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await sync_invoices_from_documents(db=db, user_id=user.id)
    await db.commit()

    query = select(Invoice).where(Invoice.user_id == user.id)
    count_query = select(func.count(Invoice.id)).where(Invoice.user_id == user.id)

    if status:
        query = query.where(Invoice.status == status)
        count_query = count_query.where(Invoice.status == status)

    if month:
        year, m = int(month[:4]), int(month[5:7])
        start = date(year, m, 1)
        end = date(year, m + 1, 1) if m < 12 else date(year + 1, 1, 1)
        query = query.where(Invoice.invoice_date >= start, Invoice.invoice_date < end)
        count_query = count_query.where(Invoice.invoice_date >= start, Invoice.invoice_date < end)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Invoice.invoice_date.desc().nulls_last(), Invoice.created_at.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    invoices = result.scalars().all()

    return InvoiceListResponse(
        invoices=[InvoiceResponse.model_validate(inv, from_attributes=True) for inv in invoices],
        total=total,
        page=page,
        pages=math.ceil(total / limit) if total else 1,
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return InvoiceResponse.model_validate(invoice, from_attributes=True)


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID,
    body: InvoiceUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    updates = body.model_dump(exclude_unset=True)
    linked_document = None
    if invoice.document_id is not None:
        document_result = await db.execute(
            select(Document).where(Document.id == invoice.document_id, Document.user_id == user.id)
        )
        linked_document = document_result.scalar_one_or_none()

    for field, value in updates.items():
        setattr(invoice, field, value)
        if linked_document is None:
            continue
        if field == "supplier_name":
            linked_document.supplier = value
        elif field == "reference":
            linked_document.reference = value
        elif field == "amount":
            linked_document.amount = value
        elif field == "vat_amount":
            linked_document.vat_amount = value
        elif field == "invoice_date":
            linked_document.document_date = value

    await db.commit()
    await db.refresh(invoice)
    return InvoiceResponse.model_validate(invoice, from_attributes=True)


@router.post("/{invoice_id}/reject")
async def reject_invoice(
    invoice_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = "rejected"
    await db.commit()
    return {"message": "Invoice rejected"}
