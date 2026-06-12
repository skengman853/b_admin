"""One-off: rebuild reconciliation matching state for given months.

Re-runs the report build with suggestion/link persistence for every user, so
persisted suggestions reflect the latest extracted financial rows.

    python scripts/rebuild_month_matching.py 2026-03 2026-04
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models import User
from app.services.transaction_reconciliation import build_reconciliation_report


async def main(months: list[str]) -> None:
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            for month in months:
                report = await build_reconciliation_report(
                    db=session,
                    user_id=user.id,
                    month=month,
                    limit=2000,
                    annotated_only=False,
                    persist_exact_matches=True,
                    persist_suggestions=True,
                )
                print(
                    f"user={user.email} month={month} "
                    f"expense_txns={report.expense_transactions} matched={report.matched_transactions} "
                    f"partial={report.partial_transactions} suggested={report.suggested_transactions} "
                    f"unmatched={report.unmatched_transactions} buckets={report.resolution_bucket_counts}",
                    flush=True,
                )
                await session.commit()
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["2026-03", "2026-04"]))
