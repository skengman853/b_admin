"""One-off: forced AI re-extraction of invoices/credit notes in a date window.

Used to correct rules-extracted amounts (e.g. Diageo discounted totals) now that
forced re-extraction consults the model with page images.

    python scripts/reextract_window_invoices.py [worker_index] [worker_count]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models import Document, User
from app.services.document_extraction import extract_documents

WINDOW_START = date(2026, 3, 15)
WINDOW_END = date(2026, 4, 30)
CHUNK = 10


async def main(worker_index: int, worker_count: int) -> None:
    tag = f"w{worker_index}"
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            ids = list(
                (
                    await session.execute(
                        select(Document.id)
                        .where(
                            Document.user_id == user.id,
                            Document.document_type.in_(["invoice", "credit_note"]),
                            Document.derivation_index == 0,
                            Document.document_date >= WINDOW_START,
                            Document.document_date <= WINDOW_END,
                            Document.extraction_status.not_in(["reviewed", "split"]),
                        )
                        .order_by(Document.created_at.asc(), Document.id.asc())
                    )
                ).scalars().all()
            )[worker_index::worker_count]
            print(f"{tag} user={user.email} invoices_to_extract={len(ids)}", flush=True)
            for start in range(0, len(ids), CHUNK):
                chunk = ids[start : start + CHUNK]
                summary = await extract_documents(
                    user=user, db=session, limit=len(chunk), document_ids=chunk, force=True
                )
                print(
                    f"{tag} user={user.email} chunk={start // CHUNK} extracted={summary['extracted']} skipped={summary['skipped']}",
                    flush=True,
                )
    print(f"{tag} ALL_DONE", flush=True)


if __name__ == "__main__":
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    asyncio.run(main(index, count))
