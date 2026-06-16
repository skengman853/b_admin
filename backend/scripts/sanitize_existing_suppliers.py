"""One-off: clean supplier names already stored on documents.

The capture path now runs detect_supplier through _sanitize_supplier, so new
documents get tidy names. Existing rows still carry the old garbage
("Canore Ltd - 09/06/2026", "Leave Request Form", operator/pub names, ...).
This re-applies the sanitiser to every document's stored supplier.

Run inside the api container:
    python scripts/sanitize_existing_suppliers.py          # dry run
    python scripts/sanitize_existing_suppliers.py --apply  # write changes
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models import Document, User
from app.services.supplier_profiles import is_operator_entity
from app.services.supplier_rules import _sanitize_supplier


async def main(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        total_changed = 0
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
            changed = 0
            for document in documents:
                old = document.supplier or ""
                # Operator/pub names belong to reattribute_operator_supplier_documents.py,
                # which recovers the real supplier from text instead of dumping to "Other".
                if is_operator_entity(old):
                    continue
                new = _sanitize_supplier(old)
                if new != old:
                    print(f"  {old!r} -> {new!r} id={document.id} name={document.attachment_name!r}", flush=True)
                    changed += 1
                    if apply:
                        document.supplier = new
            print(f"{mode} user={user.email} changed={changed} total={len(documents)}", flush=True)
            total_changed += changed
            if apply and changed:
                await session.commit()
    print(f"DONE changed={total_changed}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv[1:]))
