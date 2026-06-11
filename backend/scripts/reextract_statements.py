"""One-off: AI re-extraction of all statements so the arithmetic layer is populated.

Run inside the api container (optionally as N parallel workers over disjoint slices):
    python scripts/reextract_statements.py [worker_index] [worker_count]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models import Document, User
from app.services.document_extraction import extract_documents

CHUNK = 10


async def main(worker_index: int, worker_count: int) -> None:
    tag = f"w{worker_index}"
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            rows = (
                await session.execute(
                    select(Document.id, Document.ai_extracted_at)
                    .where(
                        Document.user_id == user.id,
                        Document.document_type == "statement",
                        Document.derivation_index == 0,
                        Document.extraction_status.not_in(["reviewed", "split"]),
                    )
                    .order_by(Document.created_at.asc(), Document.id.asc())
                )
            ).all()
            # Partition over the stable full list so concurrent workers never overlap,
            # then keep only documents not yet AI-extracted.
            ids = [doc_id for doc_id, extracted_at in rows[worker_index::worker_count] if extracted_at is None]
            print(f"{tag} user={user.email} statements_to_extract={len(ids)}", flush=True)
            for start in range(0, len(ids), CHUNK):
                chunk = list(ids[start : start + CHUNK])
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
