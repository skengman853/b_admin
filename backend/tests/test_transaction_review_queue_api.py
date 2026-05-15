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
    from app.api.transactions import get_transaction_review_queue  # noqa: E402
    from app.models import Base, Document, Transaction, User  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class TransactionReviewQueueApiTests(unittest.TestCase):
        @unittest.skip(f"transaction review queue API tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class TransactionReviewQueueApiTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="queue@example.com", password_hash="hashed")
                session.add(self.user)

                documents = [
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-match",
                        attachment_index=0,
                        attachment_name="match.pdf",
                        supplier="Matched Supplier",
                        document_type="invoice",
                        document_date=date(2026, 4, 2),
                        reference="MT100",
                        amount=Decimal("100.00"),
                        vat_amount=Decimal("16.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Matched/match.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Invoice MT100",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-partial",
                        attachment_index=0,
                        attachment_name="partial.pdf",
                        supplier="Partial Supplier",
                        document_type="invoice",
                        document_date=date(2026, 4, 3),
                        reference="PT200",
                        amount=Decimal("50.00"),
                        vat_amount=Decimal("8.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Partial/partial.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Invoice PT200",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-suggest",
                        attachment_index=0,
                        attachment_name="suggest.pdf",
                        supplier="Little Luxuries",
                        document_type="invoice",
                        document_date=date(2026, 4, 4),
                        reference="SG300",
                        amount=Decimal("200.00"),
                        vat_amount=Decimal("32.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Little Luxuries/suggest.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Little Luxuries invoice",
                    ),
                ]
                session.add_all(documents)

                transactions = [
                    Transaction(
                        user_id=self.user.id,
                        source_file="vatbook/sample.xlsx",
                        source_sheet="VAT BOOK MAR - APR",
                        row_number=10,
                        posted_account="ACC-1",
                        pub="Canal",
                        transaction_date=date(2026, 4, 10),
                        description1="Matched Supplier payment",
                        description2="bank ref",
                        debit_amount=Decimal("100.00"),
                        transaction_type="Debit",
                        category="Maintenance",
                        annotation_types=["invoice"],
                        annotation_notes=["Invoice MT100 Linked"],
                        has_linked_annotation=True,
                        raw_row_json={},
                    ),
                    Transaction(
                        user_id=self.user.id,
                        source_file="vatbook/sample.xlsx",
                        source_sheet="VAT BOOK MAR - APR",
                        row_number=11,
                        posted_account="ACC-1",
                        pub="Canal",
                        transaction_date=date(2026, 4, 11),
                        description1="Partial Supplier payment",
                        description2="bank ref",
                        debit_amount=Decimal("120.00"),
                        transaction_type="Debit",
                        category="Maintenance",
                        annotation_types=["invoice"],
                        annotation_notes=["Invoice PT200 Linked"],
                        has_linked_annotation=True,
                        raw_row_json={},
                    ),
                    Transaction(
                        user_id=self.user.id,
                        source_file="vatbook/sample.xlsx",
                        source_sheet="VAT BOOK MAR - APR",
                        row_number=12,
                        posted_account="ACC-1",
                        pub="Careys",
                        transaction_date=date(2026, 4, 12),
                        description1="Little Luxuries",
                        description2="bank ref",
                        debit_amount=Decimal("200.00"),
                        transaction_type="Debit",
                        category="Renovation",
                        annotation_types=["invoice"],
                        annotation_notes=["Invoice - Hard copy available"],
                        has_linked_annotation=False,
                        raw_row_json={},
                    ),
                    Transaction(
                        user_id=self.user.id,
                        source_file="vatbook/sample.xlsx",
                        source_sheet="VAT BOOK MAR - APR",
                        row_number=13,
                        posted_account="ACC-1",
                        pub="Careys",
                        transaction_date=date(2026, 4, 13),
                        description1="Unknown Supplier",
                        description2="bank ref",
                        debit_amount=Decimal("45.00"),
                        transaction_type="Debit",
                        category="Maintenance",
                        annotation_types=["invoice"],
                        annotation_notes=["Invoice - Hard copy available"],
                        has_linked_annotation=False,
                        raw_row_json={},
                    ),
                    Transaction(
                        user_id=self.user.id,
                        source_file="vatbook/sample.xlsx",
                        source_sheet="VAT BOOK MAR - APR",
                        row_number=14,
                        posted_account="ACC-1",
                        pub="Careys",
                        transaction_date=date(2026, 4, 14),
                        description1="Resolved Supplier",
                        description2="bank ref",
                        debit_amount=Decimal("45.00"),
                        transaction_type="Debit",
                        category="Maintenance",
                        annotation_types=["statement"],
                        annotation_notes=["Statement - Hard copy available"],
                        has_linked_annotation=False,
                        review_status="no_document_expected",
                        review_note="bank fee / no supplier doc",
                        raw_row_json={},
                    ),
                ]
                session.add_all(transactions)
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_review_queue_defaults_to_actionable_statuses_and_can_filter(self) -> None:
            async with self.session_factory() as session:
                queue = await get_transaction_review_queue(
                    month="2026-04",
                    pub=None,
                    status=None,
                    annotated_only=True,
                    persist_exact_matches=True,
                    page=1,
                    limit=20,
                    user=self.user,
                    db=session,
                )

                filtered_queue = await get_transaction_review_queue(
                    month="2026-04",
                    pub=None,
                    status="suggested,unmatched",
                    annotated_only=True,
                    persist_exact_matches=False,
                    page=1,
                    limit=20,
                    user=self.user,
                    db=session,
                )

                bucket_filtered_queue = await get_transaction_review_queue(
                    month="2026-04",
                    pub=None,
                    status=None,
                    resolution_bucket="confirm_match",
                    annotated_only=True,
                    persist_exact_matches=False,
                    page=1,
                    limit=20,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(queue.total, 3)
            self.assertEqual(queue.matched_transactions, 1)
            self.assertEqual(queue.partial_transactions, 1)
            self.assertEqual(queue.suggested_transactions, 1)
            self.assertEqual(queue.unmatched_transactions, 2)
            self.assertEqual(queue.statuses, ["partial", "suggested", "unmatched"])
            self.assertEqual(queue.resolution_bucket_counts["confirm_match"], 2)
            self.assertEqual(queue.resolution_bucket_counts["complete_partial_match"], 1)
            self.assertEqual(queue.resolution_bucket_counts["awaiting_document"], 2)
            self.assertEqual(
                [item.status for item in queue.transactions],
                ["partial", "suggested", "unmatched"],
            )
            self.assertEqual(queue.transactions[0].transaction.row_number, 11)
            self.assertEqual([link.document.reference for link in queue.transactions[0].persisted_links], ["PT200"])
            self.assertEqual([match.reference for match in queue.transactions[0].exact_matches], ["PT200"])
            self.assertTrue(all(item.needs_action for item in queue.transactions))
            self.assertEqual(queue.transactions[0].resolution_bucket, "complete_partial_match")
            self.assertIsNone(queue.transactions[0].recommended_review_status)
            self.assertEqual(queue.transactions[1].resolution_bucket, "confirm_match")
            self.assertEqual(queue.transactions[1].recommended_review_status, "linked")
            self.assertEqual(queue.transactions[2].resolution_bucket, "awaiting_document")
            self.assertEqual(queue.transactions[2].recommended_review_status, "awaiting_document")

            self.assertEqual(filtered_queue.total, 2)
            self.assertEqual(filtered_queue.statuses, ["suggested", "unmatched"])
            self.assertEqual(
                [item.status for item in filtered_queue.transactions],
                ["suggested", "unmatched"],
            )

            self.assertEqual(bucket_filtered_queue.total, 1)
            self.assertEqual(
                [item.transaction.row_number for item in bucket_filtered_queue.transactions],
                [12],
            )
            self.assertEqual(bucket_filtered_queue.transactions[0].resolution_bucket, "confirm_match")


if __name__ == "__main__":
    unittest.main()
