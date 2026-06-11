"""One-off: re-attribute documents whose supplier is one of the operator's own
pub names (e.g. "Careys Bar", "Canal Turn"). Those names identify the customer,
not the supplier, and pollute supplier-level reconciliation stats.

The real supplier is recovered from the document's extracted text, falling back
to the AI extraction payload. Documents that cannot be resolved are reported and
left unchanged.

Run inside the api container:
    python scripts/reattribute_operator_supplier_documents.py          # dry run
    python scripts/reattribute_operator_supplier_documents.py --apply  # write changes
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models import Document, User
from app.services.document_financial_backfill import backfill_document_financial_state
from app.services.supplier_profiles import (
    canonicalize_supplier_name,
    is_operator_entity,
    match_known_supplier_in_text,
)


def _resolve_supplier(document: Document) -> str | None:
    known = match_known_supplier_in_text(document.extracted_text or "")
    if known and not is_operator_entity(known):
        return known

    payload = document.ai_extraction_payload or {}
    ai_supplier = payload.get("supplier") if isinstance(payload, dict) else None
    if ai_supplier and not is_operator_entity(ai_supplier):
        return canonicalize_supplier_name(ai_supplier)

    return None


async def main(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            documents = (
                (
                    await session.execute(
                        select(Document)
                        .where(Document.user_id == user.id)
                        .order_by(Document.created_at.asc(), Document.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            affected = [doc for doc in documents if is_operator_entity(doc.supplier)]
            print(f"{mode} user={user.email} affected={len(affected)}", flush=True)

            resolved_ids = []
            for document in affected:
                supplier = _resolve_supplier(document)
                if supplier is None:
                    print(
                        f"  unresolved id={document.id} type={document.document_type} "
                        f"supplier={document.supplier!r} name={document.attachment_name!r}",
                        flush=True,
                    )
                    continue
                print(
                    f"  {document.supplier!r} -> {supplier!r} id={document.id} "
                    f"type={document.document_type} name={document.attachment_name!r}",
                    flush=True,
                )
                if apply:
                    document.supplier = supplier
                    resolved_ids.append(document.id)

            if apply and resolved_ids:
                await session.commit()
                summary = await backfill_document_financial_state(
                    user=user,
                    db=session,
                    limit=len(resolved_ids),
                    document_ids=resolved_ids,
                    force=True,
                )
                print(
                    f"  financial_state_backfilled={summary['backfilled']} skipped={summary['skipped']}",
                    flush=True,
                )
    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv[1:]))
