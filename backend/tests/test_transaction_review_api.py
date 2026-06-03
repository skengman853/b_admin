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
    from app.api.transactions import (
        apply_existing_transaction_rule,
        create_transaction_rule,
        get_transaction_detail,
        get_transaction_history,
        list_transaction_rules,
        update_transaction_review,
    )  # noqa: E402
    from app.models import Base, Transaction, TransactionReviewEvent, TransactionRule, User  # noqa: E402
    from app.schemas import (
        TransactionReviewUpdateRequest,
        TransactionRuleApplyRequest,
        TransactionRuleCreateRequest,
    )  # noqa: E402
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
                self.similar_transaction = Transaction(
                    user_id=self.user.id,
                    source_type="bank_statement",
                    source_file="bankstatements/sample.pdf",
                    source_sheet="53747-031",
                    row_number=100,
                    posted_account="93-22-64 - 53747-031",
                    pub="Careys",
                    transaction_date=date(2026, 5, 1),
                    description1="D/D Example Supplier",
                    description2="IE26050112345678",
                    debit_amount=Decimal("52.00"),
                    transaction_type="Debit",
                    raw_row_json={},
                )
                self.other_transaction = Transaction(
                    user_id=self.user.id,
                    source_type="bank_statement",
                    source_file="bankstatements/sample.pdf",
                    source_sheet="53747-031",
                    row_number=101,
                    posted_account="93-22-64 - 53747-031",
                    pub="Careys",
                    transaction_date=date(2026, 5, 2),
                    description1="D/D Different Supplier",
                    description2="IE26050212345678",
                    debit_amount=Decimal("62.00"),
                    transaction_type="Debit",
                    raw_row_json={},
                )
                session.add_all([self.user, self.transaction, self.similar_transaction, self.other_transaction])
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_update_transaction_review_persists_status_and_note(self) -> None:
            async with self.session_factory() as session:
                updated = await update_transaction_review(
                    transaction_id=self.transaction.id,
                    body=TransactionReviewUpdateRequest(
                        review_status="hard_copy_available",
                        review_note="hard copy filed in office",
                        expected_supplier="Athlone Furnit",
                    ),
                    user=self.user,
                    db=session,
                )

            self.assertEqual(updated.review_status, "hard_copy_available")
            self.assertEqual(updated.category, "Hard Copy Available")
            self.assertEqual(updated.review_note, "hard copy filed in office")
            self.assertEqual(updated.expected_supplier, "Athlone Furnit")
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
                self.assertEqual(events[0].current_review_status, "hard_copy_available")
                self.assertEqual(events[0].payload["current_category"], "Hard Copy Available")
                self.assertEqual(events[0].payload["current_expected_supplier"], "Athlone Furnit")

        async def test_detail_and_history_endpoints_return_stable_shapes(self) -> None:
            async with self.session_factory() as session:
                await update_transaction_review(
                    transaction_id=self.transaction.id,
                    body=TransactionReviewUpdateRequest(
                        review_status="hard_copy_available",
                        review_note="hard copy filed in office",
                        expected_supplier="Athlone Furnit",
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
            self.assertEqual(detail.transaction.review_status, "hard_copy_available")
            self.assertEqual(detail.transaction.category, "Hard Copy Available")
            self.assertEqual(detail.recommended_review_status, "hard_copy_available")
            self.assertEqual(
                detail.resolution_reason,
                "A hard-copy supplier document is available for this row, even though no imported PDF is linked yet",
            )
            self.assertEqual(detail.history_count, 1)
            self.assertIsNotNone(detail.reconciliation_flow)
            self.assertEqual(detail.reconciliation_flow.flow_type, "document_gap")
            self.assertGreaterEqual(len(detail.reconciliation_flow.stages), 4)
            self.assertEqual(history.transaction_id, self.transaction.id)
            self.assertEqual(len(history.events), 1)
            self.assertEqual(history.events[0].event_type, "review_updated")

        async def test_create_transaction_rule_updates_similar_transactions(self) -> None:
            async with self.session_factory() as session:
                result = await create_transaction_rule(
                    transaction_id=self.transaction.id,
                    body=TransactionRuleCreateRequest(
                        category_override="Wages",
                        review_status="handled_by_rule",
                        document_expectation="none",
                        owner_note="Wages / payroll",
                        expected_supplier="Bridget Carey",
                        apply_same_pub_only=True,
                        apply_to_existing=True,
                    ),
                    user=self.user,
                    db=session,
                )

            self.assertEqual(result.updated_transactions, 2)
            self.assertEqual(result.transaction.review_status, "handled_by_rule")
            self.assertEqual(result.transaction.category, "Wages")
            self.assertEqual(result.transaction.review_note, "Wages / payroll")
            self.assertEqual(result.transaction.expected_supplier, "Bridget Carey")

            async with self.session_factory() as session:
                refreshed_transactions = (
                    await session.scalars(
                        select(Transaction).where(Transaction.user_id == self.user.id).order_by(Transaction.row_number.asc())
                    )
                ).all()
                rules = (await session.scalars(select(TransactionRule))).all()

            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0].category_override, "Wages")
            self.assertEqual(rules[0].review_status, "handled_by_rule")
            self.assertTrue(all(transaction.review_status == "handled_by_rule" for transaction in refreshed_transactions))

        async def test_list_and_apply_existing_transaction_rule_as_template(self) -> None:
            async with self.session_factory() as session:
                created = await create_transaction_rule(
                    transaction_id=self.transaction.id,
                    body=TransactionRuleCreateRequest(
                        category_override="Contract",
                        review_status="handled_by_rule",
                        document_expectation="annual_invoice",
                        owner_note="Charged monthly, invoiced annually",
                        expected_supplier="Example Supplier",
                        apply_same_pub_only=True,
                        apply_to_existing=False,
                    ),
                    user=self.user,
                    db=session,
                )

            async with self.session_factory() as session:
                listed = await list_transaction_rules(
                    source_type="bank_statement",
                    pub="Careys",
                    user=self.user,
                    db=session,
                )
                filtered_list = await list_transaction_rules(
                    source_type="bank_statement",
                    pub="Careys",
                    transaction_id=self.other_transaction.id,
                    user=self.user,
                    db=session,
                )
                applied = await apply_existing_transaction_rule(
                    transaction_id=self.other_transaction.id,
                    body=TransactionRuleApplyRequest(rule_id=created.rule.id),
                    user=self.user,
                    db=session,
                )

            async with self.session_factory() as session:
                rules = (
                    await session.scalars(
                        select(TransactionRule)
                        .where(TransactionRule.user_id == self.user.id)
                        .order_by(TransactionRule.created_at.asc())
                    )
                ).all()

            self.assertEqual(len(listed.rules), 1)
            self.assertEqual(len(filtered_list.rules), 1)
            self.assertEqual(listed.rules[0].id, created.rule.id)
            self.assertEqual(filtered_list.rules[0].id, created.rule.id)
            self.assertNotEqual(applied.rule.id, created.rule.id)
            self.assertEqual(applied.transaction.review_status, "handled_by_rule")
            self.assertEqual(applied.transaction.category, "Contract")
            self.assertEqual(applied.transaction.review_note, "Charged monthly, invoiced annually")
            self.assertEqual(applied.transaction.expected_supplier, "Example Supplier")
            self.assertEqual(len(rules), 2)
            self.assertEqual(rules[1].display_label, "D/D Different Supplier")
            self.assertEqual(rules[1].category_override, "Contract")


if __name__ == "__main__":
    unittest.main()
