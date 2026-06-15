"""One-off: copy the operator's invoice/statement references from the hand-made
VAT-book rows onto the matching bank-statement transactions, then re-run the
matcher.

Bank statements are the source of truth for transactions, but the reference
notes the operator wrote ("Invoice - Diageo Inv 9263305332 ...") live on the
vatbook rows. Copying them onto the bank twins restores the rich
invoice/statement matching on the source-of-truth transactions. Idempotent:
only fills bank rows that have no notes yet.

    python scripts/bridge_vatbook_notes.py [pub]
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models import Transaction, User
from app.services.transaction_reconciliation import build_reconciliation_report


def _key(t: Transaction):
    return (t.pub, t.transaction_date, str(t.debit_amount) if t.debit_amount is not None else None)


async def main(pub: str | None) -> None:
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            base = select(Transaction).where(Transaction.user_id == user.id)
            if pub:
                base = base.where(Transaction.pub == pub)

            bank = [
                t for t in (await session.execute(base.where(Transaction.source_type == "bank_statement"))).scalars().all()
                if t.debit_amount is not None
            ]
            vb = [
                t for t in (await session.execute(base.where(Transaction.source_type == "vatbook"))).scalars().all()
                if t.debit_amount is not None and t.annotation_notes
            ]
            if not bank:
                continue

            vb_by_key: dict = defaultdict(list)
            for t in sorted(vb, key=lambda x: x.row_number):
                vb_by_key[_key(t)].append(t)
            bank_by_key: dict = defaultdict(list)
            for t in sorted(bank, key=lambda x: x.row_number):
                bank_by_key[_key(t)].append(t)

            copied = 0
            for key, bank_group in bank_by_key.items():
                vb_group = vb_by_key.get(key, [])
                for i in range(min(len(bank_group), len(vb_group))):
                    bt = bank_group[i]
                    if bt.annotation_notes:  # already has notes — leave it
                        continue
                    src = vb_group[i]
                    bt.annotation_notes = list(src.annotation_notes or [])
                    bt.annotation_types = list(src.annotation_types or [])
                    bt.has_linked_annotation = True
                    copied += 1
            await session.commit()

            months = sorted({t.transaction_date.strftime("%Y-%m") for t in bank if t.transaction_date})
            print(f"user={user.email} notes_copied={copied} months={months}", flush=True)
            for month in months:
                report = await build_reconciliation_report(
                    db=session, user_id=user.id, month=month, pub=pub, limit=2000,
                    annotated_only=False, persist_exact_matches=True, persist_suggestions=True,
                )
                await session.commit()
                print(f"  {month}: matched={report.matched_transactions} partial={report.partial_transactions} "
                      f"suggested={report.suggested_transactions} unmatched={report.unmatched_transactions}", flush=True)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
