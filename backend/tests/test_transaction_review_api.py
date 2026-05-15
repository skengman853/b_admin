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
    from sqlalchemy import select  # noqa: E402
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
    from app.api.transactions import get_transaction_detail, get_transaction_history, update_transaction_review  # noqa: E402
    from app.models import Base, Transaction, TransactionReviewEvent, User  # noqa: E402
    from app.schemas import TransactionReviewUpdateRequest  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class TransactionReviewApiTests(unittest.TestCase):
        @unittest.skip(f"transaction review API tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class TransactionReviewApiTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="review@example.com", password_hash="hashed")
                self.transaction = Transaction(
                    user_id=self.user.id,
                    source_type="bank_statement",
                    source_file="bankstatements/sample.pdf",
                    source_sheet="53747-031",
                    row_number=99,
                    posted_account="93-22-64 - 53747-031",
                    pub="Careys",
                    transaction_date=date(2026, 4, 30),
                    description1="D/D Example Supplier",
                    description2="IE26043012345678",
                    debit_amount=Decimal("42.00"),
                    transaction_type="Debit",
                    raw_row_json={},
                )
                session.add_all([self.user, self.transaction])
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_update_transaction_review_persists_status_and_note(self) -> None:
            async with self.session_factory() as session:
                updated = await update_transaction_review(
                    transaction_id=self.transaction.id,
                    body=TransactionReviewUpdateRequest(
                        review_status="awaiting_document",
                        review_note="supplier invoice not received yet",
                        expected_supplier="Bulmers",
                    ),
                    user=self.user,
                    db=session,
                )

            self.assertEqual(updated.review_status, "awaiting_document")
            self.assertEqual(updated.review_note, "supplier invoice not received yet")
            self.assertEqual(updated.expected_supplier, "Bulmers")
            self.assertIsNotNone(updated.reviewed_at)

            async with self.session_factory() as session:
                events = (
                    await session.scalars(
                        select(TransactionReviewEvent).where(
                            TransactionReviewEvent.transaction_id == self.transaction.id
                        )
                    )
                ).all()
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].event_type, "review_updated")
                self.assertEqual(events[0].previous_review_status, "pending")
                self.assertEqual(events[0].current_review_status, "awaiting_document")
                self.assertEqual(events[0].payload["current_expected_supplier"], "Bulmers")

        async def test_detail_and_history_endpoints_return_stable_shapes(self) -> None:
            async with self.session_factory() as session:
                await update_transaction_review(
                    transaction_id=self.transaction.id,
                    body=TransactionReviewUpdateRequest(
                        review_status="awaiting_document",
                        review_note="supplier invoice not received yet",
                        expected_supplier="Bulmers",
                    ),
                    user=self.user,
                    db=session,
                )

            async with self.session_factory() as session:
                detail = await get_transaction_detail(
                    transaction_id=self.transaction.id,
                    persist_exact_matches=False,
                    user=self.user,
                    db=session,
                )
                history = await get_transaction_history(
                    transaction_id=self.transaction.id,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(detail.transaction.id, self.transaction.id)
            self.assertEqual(detail.transaction.review_status, "awaiting_document")
            self.assertEqual(detail.history_count, 1)
            self.assertIsNotNone(detail.reconciliation_flow)
            self.assertEqual(detail.reconciliation_flow.flow_type, "document_gap")
            self.assertGreaterEqual(len(detail.reconciliation_flow.stages), 4)
            self.assertEqual(history.transaction_id, self.transaction.id)
            self.assertEqual(len(history.events), 1)
            self.assertEqual(history.events[0].event_type, "review_updated")


if __name__ == "__main__":
    unittest.main()
