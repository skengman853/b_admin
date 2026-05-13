from __future__ import annotations

import sys
import types
import unittest
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pydantic_settings" not in sys.modules:
    fake_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - tiny test shim
        def __init__(self, **_: object) -> None:
            pass

    fake_module.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = fake_module

_missing_dependencies: str | None = None

try:
    import aiosqlite  # noqa: F401,E402
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
    from app.api.transactions import (  # noqa: E402
        create_transaction_link,
        get_transaction_links,
        update_transaction_link,
    )
    from app.models import Base, Document, Transaction, User  # noqa: E402
    from app.schemas import TransactionLinkCreateRequest, TransactionLinkUpdateRequest  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class TransactionLinksApiTests(unittest.TestCase):
        @unittest.skip(f"transaction link API tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class TransactionLinksApiTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="links@example.com", password_hash="hashed")
                session.add(self.user)

                self.exact_document = Document(
                    user_id=self.user.id,
                    gmail_message_id="doc-exact",
                    attachment_index=0,
                    attachment_name="exact.pdf",
                    supplier="Exact Supplier",
                    document_type="invoice",
                    document_date=date(2026, 4, 2),
                    reference="EX100",
                    amount=Decimal("100.00"),
                    vat_amount=Decimal("16.00"),
                    confidence_score=0.99,
                    extraction_status="extracted",
                    local_path="Documents/Exact/exact.pdf",
                    needs_review=False,
                    review_reasons=[],
                    source_email_subject="Invoice EX100",
                )
                self.manual_document = Document(
                    user_id=self.user.id,
                    gmail_message_id="doc-manual",
                    attachment_index=0,
                    attachment_name="manual.pdf",
                    supplier="Manual Supplier",
                    document_type="invoice",
                    document_date=date(2026, 4, 3),
                    reference="MN200",
                    amount=Decimal("55.00"),
                    vat_amount=Decimal("9.00"),
                    confidence_score=0.99,
                    extraction_status="extracted",
                    local_path="Documents/Manual/manual.pdf",
                    needs_review=False,
                    review_reasons=[],
                    source_email_subject="Invoice MN200",
                )
                self.transaction = Transaction(
                    user_id=self.user.id,
                    source_file="vatbook/sample.xlsx",
                    source_sheet="VAT BOOK MAR - APR",
                    row_number=22,
                    posted_account="ACC-1",
                    pub="Canal",
                    transaction_date=date(2026, 4, 10),
                    description1="Exact Supplier payment",
                    description2="bank ref",
                    debit_amount=Decimal("100.00"),
                    transaction_type="Debit",
                    category="Maintenance",
                    annotation_types=["invoice"],
                    annotation_notes=["Invoice EX100 Linked"],
                    has_linked_annotation=True,
                    raw_row_json={},
                )
                session.add_all([self.exact_document, self.manual_document, self.transaction])
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_get_links_can_persist_exact_matches_and_manual_link_can_be_updated(self) -> None:
            async with self.session_factory() as session:
                initial = await get_transaction_links(
                    transaction_id=self.transaction.id,
                    persist_exact_matches=True,
                    user=self.user,
                    db=session,
                )

                self.assertEqual(initial.status, "matched")
                self.assertEqual(len(initial.exact_matches), 1)
                self.assertEqual(initial.exact_matches[0].reference, "EX100")
                self.assertEqual(len(initial.persisted_links), 1)
                self.assertEqual(initial.persisted_links[0].document.reference, "EX100")
                self.assertEqual(initial.persisted_links[0].status, "confirmed")

                created = await create_transaction_link(
                    transaction_id=self.transaction.id,
                    body=TransactionLinkCreateRequest(
                        document_id=self.manual_document.id,
                        role="invoice",
                        status="suggested",
                        score=0.72,
                        confidence="medium",
                        match_reason="Manual review seed",
                        amount_applied=Decimal("55.00"),
                        note="created in test",
                    ),
                    user=self.user,
                    db=session,
                )
                self.assertEqual(created.document.reference, "MN200")
                self.assertEqual(created.status, "suggested")

                after_create = await get_transaction_links(
                    transaction_id=self.transaction.id,
                    persist_exact_matches=False,
                    user=self.user,
                    db=session,
                )
                self.assertEqual(after_create.transaction.review_status, "pending")

                updated = await update_transaction_link(
                    link_id=created.id,
                    body=TransactionLinkUpdateRequest(
                        status="confirmed",
                        note="confirmed manual document",
                    ),
                    user=self.user,
                    db=session,
                )
                self.assertEqual(updated.status, "confirmed")
                self.assertEqual(updated.note, "confirmed manual document")

                after_confirm = await get_transaction_links(
                    transaction_id=self.transaction.id,
                    persist_exact_matches=False,
                    user=self.user,
                    db=session,
                )
                self.assertEqual(after_confirm.transaction.review_status, "linked")

                updated = await update_transaction_link(
                    link_id=created.id,
                    body=TransactionLinkUpdateRequest(
                        status="rejected",
                        note="not the right document",
                    ),
                    user=self.user,
                    db=session,
                )
                self.assertEqual(updated.status, "rejected")
                self.assertEqual(updated.note, "not the right document")

                refreshed = await get_transaction_links(
                    transaction_id=self.transaction.id,
                    persist_exact_matches=False,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(len(refreshed.persisted_links), 2)
            self.assertEqual(refreshed.transaction.review_status, "pending")
            self.assertEqual(
                [link.status for link in refreshed.persisted_links],
                ["confirmed", "rejected"],
            )
            self.assertEqual(
                [link.document.reference for link in refreshed.persisted_links],
                ["EX100", "MN200"],
            )


if __name__ == "__main__":
    unittest.main()
