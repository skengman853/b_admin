from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import User, Invoice
from app.schemas import DashboardSummary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    month: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
