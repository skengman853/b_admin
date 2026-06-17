"""Background jobs run on the Celery worker.

The worker has no HTTP request timeout, so long operations (extraction over
hundreds of documents) run here to completion instead of being babysat in
chunks from the browser. Progress is reported via Celery task state and read
back through the job-status endpoint.

The pipeline code is async (AsyncSession); Celery tasks are sync, so each task
runs its coroutine on a fresh event loop with its own engine to avoid binding
the app's global engine to a worker loop.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Document, User
from app.services.document_extraction import extract_documents
from app.tasks.celery_app import celery_app

_CHUNK = 10  # commit/progress checkpoint size


def _run(coro):
    return asyncio.run(coro)


@celery_app.task(bind=True, name="extract_documents_job")
def extract_documents_job(self, user_id: str, force: bool = False):
    return _run(_extract_all(self, user_id, force))


async def _extract_all(task, user_id: str, force: bool) -> dict:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    extracted = 0
    skipped = 0
    try:
        async with session_factory() as db:
            user = (
                await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
            ).scalar_one()

            # Pre-select the documents to process once, then walk them in chunks
            # by id — stable totals for progress, and no risk of re-selecting the
            # same rows (which the force path would otherwise do).
            candidates = select(Document.id).where(
                Document.user_id == user.id,
                Document.derivation_index == 0,
                Document.extraction_status != "split",
            )
            if not force:
                candidates = candidates.where(
                    Document.extraction_status.not_in(["extracted", "reviewed", "split", "failed"])
                )
            ids = list(
                (await db.execute(candidates.order_by(Document.created_at.asc()))).scalars().all()
            )
            total = len(ids)
            task.update_state(state="PROGRESS", meta={"extracted": 0, "skipped": 0, "done": 0, "total": total})

            for start in range(0, total, _CHUNK):
                chunk = ids[start : start + _CHUNK]
                result = await extract_documents(
                    user=user, db=db, limit=len(chunk), document_ids=chunk, force=force
                )
                extracted += result["extracted"]
                skipped += result["skipped"]
                task.update_state(
                    state="PROGRESS",
                    meta={
                        "extracted": extracted,
                        "skipped": skipped,
                        "done": start + len(chunk),
                        "total": total,
                    },
                )
    finally:
        await engine.dispose()

    return {"extracted": extracted, "skipped": skipped, "total": extracted + skipped}
