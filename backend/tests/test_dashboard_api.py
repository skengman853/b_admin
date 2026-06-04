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
    from app.api.dashboard import get_document_storage_summary, get_statement_workbench, get_supplier_document_inventory, list_suppliers  # noqa: E402
    from app.models import Base, Document, Transaction, User  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class DashboardApiTests(unittest.TestCase):
        @unittest.skip(f"dashboard API tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class DashboardApiTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="dash@example.com", password_hash="hashed")
                session.add(self.user)
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="canore-march-statement",
                            attachment_index=0,
                            attachment_name="statement-march.pdf",
                            supplier="Canore Ltd",
                            document_type="statement",
                            document_date=date(2026, 3, 31),
                            amount=Decimal("457.27"),
                            extraction_status="extracted",
                            storage_provider="s3",
                            storage_bucket="test-bucket",
                            storage_key="documents/Canore/statement-march.pdf",
                            local_path="Documents/Canore Ltd/Careys/Statements/statement-march.pdf",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="canore-april-invoice",
                            attachment_index=0,
                            attachment_name="invoice-april.pdf",
                            supplier="Canore Ltd",
                            document_type="invoice",
                            document_date=date(2026, 4, 2),
                            reference="CAN-100",
                            amount=Decimal("91.45"),
                            extraction_status="extracted",
                            storage_provider="s3",
                            storage_bucket="test-bucket",
                            storage_key="documents/Canore/invoice-april.pdf",
                            drive_file_id="drive-canore-april",
                            drive_web_link="https://drive.example/canore-april",
                            local_path="Documents/Canore Ltd/Careys/Invoices/invoice-april.pdf",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="other-supplier",
                            attachment_index=0,
                            attachment_name="other.pdf",
                            supplier="Other Supplier",
                            document_type="invoice",
                            document_date=date(2026, 4, 3),
                            amount=Decimal("50.00"),
                            extraction_status="extracted",
                            local_path="Documents/Other Supplier/Invoices/other.pdf",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="canal-supplier",
                            attachment_index=0,
                            attachment_name="canal.pdf",
                            supplier="Canal Supplier",
                            document_type="statement",
                            document_date=date(2026, 4, 5),
                            amount=Decimal("70.00"),
                            extraction_status="extracted",
                            drive_file_id="drive-canal",
                            drive_web_link="https://drive.example/canal",
                            local_path="Documents/Canal Supplier/Canal/Statements/canal.pdf",
                        ),
                    ]
                )
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_supplier_document_inventory_matches_alias_and_month_window(self) -> None:
            async with self.session_factory() as session:
                payload = await get_supplier_document_inventory(
                    supplier="CanoreLTD",
                    month="2026-04",
                    pub="Careys",
                    window_months=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.supplier_query, "CanoreLTD")
            self.assertEqual(payload.canonical_supplier, "CanoreLTD")
            self.assertEqual(payload.total_documents, 2)
            self.assertEqual(payload.counts_by_type["statement"], 1)
            self.assertEqual(payload.counts_by_type["invoice"], 1)
            self.assertEqual(payload.counts_by_storage["r2_only"], 1)
            self.assertEqual(payload.counts_by_storage["r2_and_drive"], 1)
            self.assertEqual(payload.available_months, ["2026-03", "2026-04"])
            self.assertEqual([document.supplier for document in payload.documents], ["Canore Ltd", "Canore Ltd"])
            self.assertTrue(all(document.pub_hint == "Careys" for document in payload.documents))
            self.assertEqual(payload.documents[0].storage_state, "r2_only")
            self.assertEqual(payload.documents[1].storage_state, "r2_and_drive")

        async def test_supplier_document_inventory_can_filter_specific_months(self) -> None:
            async with self.session_factory() as session:
                payload = await get_supplier_document_inventory(
                    supplier="CanoreLTD",
                    month="2026-04",
                    months="2026-03",
                    pub="Careys",
                    window_months=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.selected_months, ["2026-03"])
            self.assertEqual(payload.total_documents, 1)
            self.assertEqual(payload.documents[0].document_type, "statement")
            self.assertEqual(payload.documents[0].document_date, date(2026, 3, 31))

        async def test_list_suppliers_returns_distinct_options_and_pub_filter(self) -> None:
            async with self.session_factory() as session:
                all_suppliers = await list_suppliers(
                    pub=None,
                    user=self.user,
                    db=session,
                )
                careys_suppliers = await list_suppliers(
                    pub="Careys",
                    user=self.user,
                    db=session,
                )

            self.assertTrue(any(item.supplier == "Canore Ltd" and item.document_count == 2 for item in all_suppliers.suppliers))
            self.assertTrue(any(item.supplier == "Canal Supplier" for item in all_suppliers.suppliers))
            self.assertTrue(any(item.supplier == "Canore Ltd" for item in careys_suppliers.suppliers))
            self.assertFalse(any(item.supplier == "Canal Supplier" for item in careys_suppliers.suppliers))

        async def test_document_storage_summary_counts_storage_states(self) -> None:
            async with self.session_factory() as session:
                payload = await get_document_storage_summary(
                    month="2026-04",
                    pub=None,
                    window_months=1,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total_documents, 4)
            self.assertEqual(payload.local_only, 1)
            self.assertEqual(payload.r2_only, 1)
            self.assertEqual(payload.drive_only, 1)
            self.assertEqual(payload.r2_and_drive, 1)

        async def test_statement_workbench_surfaces_imported_refs_and_likely_transactions(self) -> None:
            async with self.session_factory() as session:
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="heineken-statement-workbench",
                            attachment_index=0,
                            attachment_name="heineken-may-statement.pdf",
                            supplier="Heineken",
                            document_type="statement",
                            document_date=date(2026, 4, 2),
                            reference="Summary",
                            extraction_status="extracted",
                            storage_provider="s3",
                            storage_bucket="test-bucket",
                            storage_key="documents/Heineken/Statements/heineken-may-statement.pdf",
                            local_path="Documents/Heineken/Careys/Statements/heineken-may-statement.pdf",
                            ai_extraction_payload={
                                "supplier": "Heineken",
                                "document_type": "statement",
                                "document_date": "2026-04-02",
                                "statement_kind": "supplier_statement",
                                "is_financial": True,
                                "period_start": "2026-03-01",
                                "period_end": "2026-03-31",
                                "entries": [
                                    {
                                        "event_date": "2026-03-04",
                                        "reference": "0194101304",
                                        "transaction_type": "Invoice",
                                        "due_date": "2026-03-04",
                                        "clearing_reference": "1800043903",
                                        "amount": "3719.56",
                                    },
                                    {
                                        "event_date": "2026-03-04",
                                        "reference": "0194101305",
                                        "transaction_type": "Invoice",
                                        "due_date": "2026-03-04",
                                        "clearing_reference": "1800043907",
                                        "amount": "37.33",
                                    },
                                    {
                                        "event_date": "2026-03-04",
                                        "reference": "0194101306",
                                        "transaction_type": "Invoice",
                                        "due_date": "2026-03-04",
                                        "clearing_reference": "1800043911",
                                        "amount": "59.73",
                                    },
                                    {
                                        "event_date": "2026-03-06",
                                        "reference": "2000025959",
                                        "transaction_type": "Payment",
                                        "due_date": "2026-03-06",
                                        "amount": "3816.62",
                                    },
                                ],
                            },
                            extracted_text=(
                                "STATEMENT OF ACCOUNT\n\n"
                                "Careys Bar Limited\n"
                                "Date: 02.04.2026\n"
                                "Please find below your account statement with all items between 01.03.2026 To 31.03.2026:\n"
                                "Reference\nNumber\nDocument\nNumber\nDocument\nType\nDocument\nDate\nDue\nDate\nOriginal\nAmount\nResidual\nB/F\nAdjusted\nAmount\nBalance\n"
                                "1800043903\n\n"
                                "0194101304 Invoice\n\n"
                                "04.03.2026\n\n"
                                "04.03.2026\n\n"
                                "3,719.56\n\n"
                                "0.00\n\n"
                                "-3,719.56\n\n"
                                "0.00\n\n"
                                "1800043907\n\n"
                                "0194101305 Invoice\n\n"
                                "04.03.2026\n\n"
                                "04.03.2026\n\n"
                                "37.33\n\n"
                                "0.00\n\n"
                                "-37.33\n\n"
                                "0.00\n\n"
                                "1800043911\n\n"
                                "0194101306 Invoice\n\n"
                                "04.03.2026\n\n"
                                "04.03.2026\n\n"
                                "59.73\n\n"
                                "0.00\n\n"
                                "-59.73\n\n"
                                "0.00\n\n"
                                "2000025959\n\n"
                                "Payment\n\n"
                                "06.03.2026\n\n"
                                "06.03.2026\n\n"
                                "-3,816.62\n\n"
                                "0.00\n\n"
                                "3,816.62\n\n"
                                "0.00\n"
                            ),
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="heineken-invoice-workbench",
                            attachment_index=0,
                            attachment_name="heineken-194101304.pdf",
                            supplier="Heineken",
                            document_type="invoice",
                            document_date=date(2026, 3, 4),
                            reference="194101304",
                            amount=Decimal("3719.56"),
                            extraction_status="extracted",
                            storage_provider="s3",
                            storage_bucket="test-bucket",
                            storage_key="documents/Heineken/Invoices/heineken-194101304.pdf",
                            local_path="Documents/Heineken/Careys/Invoices/heineken-194101304.pdf",
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=88,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 3, 6),
                            description1="D/D HEINEKEN IRELA",
                            description2="IE26040200000000",
                            debit_amount=Decimal("3816.62"),
                            transaction_type="Debit",
                            category=None,
                            annotation_types=[],
                            annotation_notes=[],
                            has_linked_annotation=False,
                            raw_row_json={},
                        ),
                    ]
                )
                await session.commit()

                payload = await get_statement_workbench(
                    supplier="Heineken",
                    month="2026-03",
                    pub="Careys",
                    window_months=1,
                    limit=20,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total_statements, 1)
            self.assertIn("0194101304", payload.statements[0].imported_invoice_refs)
            self.assertGreaterEqual(payload.total_likely_transactions, 1)
            self.assertTrue(any(transaction.row_number == 88 for transaction in payload.statements[0].likely_transactions))

        async def test_statement_workbench_does_not_keep_late_proximity_only_transactions(self) -> None:
            async with self.session_factory() as session:
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="connacht-march-statement-workbench",
                            attachment_index=0,
                            attachment_name="connacht-march-statement.pdf",
                            supplier="Connacht Bottlers",
                            document_type="statement",
                            document_date=date(2026, 3, 31),
                            reference="057",
                            extraction_status="extracted",
                            storage_provider="s3",
                            storage_bucket="test-bucket",
                            storage_key="documents/Connacht/Statements/057.pdf",
                            local_path="Documents/Connacht Bottlers/Careys/Statements/057.pdf",
                            ai_extraction_payload={
                                "supplier": "Connacht Bottlers",
                                "document_type": "statement",
                                "document_date": "2026-03-31",
                                "statement_kind": "trade_statement",
                                "is_financial": True,
                                "period_start": "2026-03-01",
                                "period_end": "2026-03-31",
                                "entries": [
                                    {
                                        "event_date": "2026-03-25",
                                        "reference": "33404",
                                        "transaction_type": "Invoice",
                                        "due_date": "2026-03-25",
                                        "amount": "350.33",
                                    }
                                ],
                            },
                            extracted_text="Trade account statement 01/03/2026 to 31/03/2026",
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=36,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 1),
                            description1="D/D CONNACHT BOTTL",
                            description2="IE26040144045913",
                            debit_amount=Decimal("350.33"),
                            transaction_type="Debit",
                            category=None,
                            annotation_types=[],
                            annotation_notes=[],
                            has_linked_annotation=False,
                            raw_row_json={},
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=38,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 16),
                            description1="D/D CONNACHT BOTTL",
                            description2="IE26041644045913",
                            debit_amount=Decimal("169.74"),
                            transaction_type="Debit",
                            category=None,
                            annotation_types=[],
                            annotation_notes=[],
                            has_linked_annotation=False,
                            raw_row_json={},
                        ),
                    ]
                )
                await session.commit()

                payload = await get_statement_workbench(
                    supplier="Connacht Bottlers",
                    month="2026-04",
                    pub="Careys",
                    window_months=1,
                    limit=20,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total_statements, 1)
            likely_rows = [transaction.row_number for transaction in payload.statements[0].likely_transactions]
            self.assertIn(36, likely_rows)
            self.assertNotIn(38, likely_rows)


if __name__ == "__main__":
    unittest.main()
