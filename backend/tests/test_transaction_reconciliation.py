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
    from app.models import Base, Document, Transaction, TransactionDocumentLink, User  # noqa: E402
    from app.services.transaction_reconciliation import (  # noqa: E402
        AUTO_EXACT_LINK_NOTE,
        build_reconciliation_report,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class TransactionReconciliationTests(unittest.TestCase):
        @unittest.skip(f"transaction reconciliation tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class TransactionReconciliationTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="reconcile@example.com", password_hash="hashed")
                session.add(self.user)

                documents = [
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-ex-100",
                        attachment_index=0,
                        attachment_name="exact_100.pdf",
                        supplier="Exact Supplier",
                        document_type="invoice",
                        document_date=date(2026, 4, 1),
                        reference="EX100",
                        amount=Decimal("60.00"),
                        vat_amount=Decimal("10.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Exact/exact_100.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Exact Supplier EX100",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-ex-101",
                        attachment_index=0,
                        attachment_name="exact_101.pdf",
                        supplier="Exact Supplier",
                        document_type="invoice",
                        document_date=date(2026, 4, 2),
                        reference="EX101",
                        amount=Decimal("40.00"),
                        vat_amount=Decimal("6.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Exact/exact_101.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Exact Supplier EX101",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-px-200",
                        attachment_index=0,
                        attachment_name="partial_200.pdf",
                        supplier="Partial Supplier",
                        document_type="invoice",
                        document_date=date(2026, 4, 3),
                        reference="PX200",
                        amount=Decimal("50.00"),
                        vat_amount=Decimal("8.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Partial/partial_200.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Partial Supplier PX200",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-sg-300",
                        attachment_index=0,
                        attachment_name="little_luxuries_invoice_300.pdf",
                        supplier="Little Luxuries",
                        document_type="invoice",
                        document_date=date(2026, 4, 5),
                        reference="SG300",
                        amount=Decimal("200.00"),
                        vat_amount=Decimal("32.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Little Luxuries/sg300.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Little Luxuries invoice",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-gr-400",
                        attachment_index=0,
                        attachment_name="grouped_supplies_400.pdf",
                        supplier="Grouped Supplies",
                        document_type="invoice",
                        document_date=date(2026, 4, 7),
                        reference="GR400",
                        amount=Decimal("80.00"),
                        vat_amount=Decimal("12.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Grouped/gr400.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Grouped Supplies invoice 400",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-gr-401",
                        attachment_index=0,
                        attachment_name="grouped_supplies_401.pdf",
                        supplier="Grouped Supplies",
                        document_type="invoice",
                        document_date=date(2026, 4, 8),
                        reference="GR401",
                        amount=Decimal("70.00"),
                        vat_amount=Decimal("11.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Grouped/gr401.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Grouped Supplies invoice 401",
                    ),
                    Document(
                        user_id=self.user.id,
                        gmail_message_id="doc-other",
                        attachment_index=0,
                        attachment_name="other.pdf",
                        supplier="Other Supplier",
                        document_type="invoice",
                        document_date=date(2026, 4, 20),
                        reference="OT900",
                        amount=Decimal("90.00"),
                        vat_amount=Decimal("14.00"),
                        confidence_score=0.99,
                        extraction_status="extracted",
                        local_path="Documents/Other/ot900.pdf",
                        needs_review=False,
                        review_reasons=[],
                        source_email_subject="Other Supplier invoice",
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
                        description1="Exact Supplier payment",
                        description2="bank ref",
                        debit_amount=Decimal("100.00"),
                        transaction_type="Debit",
                        category="Maintenance",
                        annotation_types=["invoice", "invoice"],
                        annotation_notes=["Invoice EX100 Linked", "Invoice EX101 Linked"],
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
                        annotation_notes=["Invoice PX200 Linked"],
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
                        transaction_date=date(2026, 4, 10),
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
                        transaction_date=date(2026, 4, 9),
                        description1="Grouped Supplies",
                        description2="bank ref",
                        debit_amount=Decimal("150.00"),
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
                        pub="Canal",
                        transaction_date=date(2026, 4, 15),
                        description1="B & Q",
                        description2="bank ref",
                        debit_amount=Decimal("30.00"),
                        transaction_type="Debit",
                        category="Maintenance",
                        annotation_types=["receipt"],
                        annotation_notes=["Receipt - Hard copy available"],
                        has_linked_annotation=False,
                        raw_row_json={},
                    ),
                    Transaction(
                        user_id=self.user.id,
                        source_type="bank_statement",
                        source_file="bankstatements/sample.pdf",
                        source_sheet="53747-031",
                        row_number=1,
                        posted_account="93-22-64 - 53747-031",
                        pub="Careys",
                        transaction_date=date(2026, 4, 21),
                        description1="D/D Test Supplier",
                        description2="IE26042100000000",
                        debit_amount=Decimal("90.00"),
                        transaction_type="Debit",
                        category=None,
                        annotation_types=[],
                        annotation_notes=[],
                        has_linked_annotation=False,
                        raw_row_json={},
                    ),
                ]
                session.add_all(transactions)
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_report_sorts_and_persists_exact_links_and_supports_grouped_suggestions(self) -> None:
            async with self.session_factory() as session:
                report = await build_reconciliation_report(
                    db=session,
                    user_id=self.user.id,
                    month="2026-04",
                    source_type="vatbook",
                    limit=10,
                    annotated_only=True,
                    persist_exact_matches=True,
                )
                await session.commit()

                links = (
                    await session.execute(
                        select(TransactionDocumentLink).where(
                            TransactionDocumentLink.user_id == self.user.id
                        )
                    )
                ).scalars().all()

            self.assertEqual(report.matched_transactions, 1)
            self.assertEqual(report.partial_transactions, 1)
            self.assertEqual(report.suggested_transactions, 2)
            self.assertEqual(report.unmatched_transactions, 1)
            self.assertEqual(report.total_transactions, 5)

            statuses = [item.status for item in report.transactions]
            self.assertEqual(statuses[:5], ["matched", "partial", "suggested", "suggested", "unmatched"])

            matched_item = next(item for item in report.transactions if item.row_number == 10)
            self.assertEqual(len(matched_item.exact_matches), 2)
            self.assertEqual({match.reference for match in matched_item.exact_matches}, {"EX100", "EX101"})

            partial_item = next(item for item in report.transactions if item.row_number == 11)
            self.assertEqual(partial_item.status, "partial")
            self.assertEqual([match.reference for match in partial_item.exact_matches], ["PX200"])

            single_suggested_item = next(item for item in report.transactions if item.row_number == 12)
            self.assertEqual(single_suggested_item.status, "suggested")
            self.assertEqual([match.reference for match in single_suggested_item.suggested_matches], ["SG300"])

            grouped_item = next(item for item in report.transactions if item.row_number == 13)
            self.assertEqual(grouped_item.status, "suggested")
            self.assertEqual(
                {match.reference for match in grouped_item.suggested_matches},
                {"GR400", "GR401"},
            )

            self.assertEqual(len(links), 3)
            self.assertTrue(all(link.note == AUTO_EXACT_LINK_NOTE for link in links))
            self.assertTrue(all(link.status == "confirmed" for link in links))
            self.assertEqual(
                {(str(link.amount_applied), link.document_id is not None) for link in links},
                {("60.00", True), ("40.00", True), ("50.00", True)},
            )

        async def test_bank_statement_matching_requires_supplier_alignment_and_supports_aliases(self) -> None:
            async with self.session_factory() as session:
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-aa-100",
                            attachment_index=0,
                            attachment_name="automatic_amusements_112020.pdf",
                            supplier="Automatic Amusements",
                            document_type="invoice",
                            document_date=date(2026, 4, 28),
                            reference="112020",
                            amount=Decimal("98.40"),
                            vat_amount=Decimal("18.40"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Automatic Amusements/112020.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Automatic Amusements invoice 112020",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-cb-100",
                            attachment_index=0,
                            attachment_name="connacht_bottlers_cb100.pdf",
                            supplier="Connacht Bottlers",
                            document_type="invoice",
                            document_date=date(2026, 4, 1),
                            reference="CB100",
                            amount=Decimal("389.77"),
                            vat_amount=Decimal("57.00"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Connacht Bottlers/cb100.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Connacht Bottlers invoice CB100",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-cb-statement",
                            attachment_index=0,
                            attachment_name="CAREY01-Statement.pdf",
                            supplier="Connacht Bottlers",
                            document_type="statement",
                            document_date=date(2026, 4, 30),
                            reference=None,
                            amount=Decimal("1527.48"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Connacht Bottlers/statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Connacht Bottlers Statement",
                            source_email_sender="Info - Connacht Bottlers <info@connachtbottlers.ie>",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-boc-statement",
                            attachment_index=0,
                            attachment_name="boc_statement.pdf",
                            supplier="BOC",
                            document_type="statement",
                            document_date=date(2026, 4, 30),
                            reference=None,
                            amount=Decimal("500.00"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/BOC/statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="BOC Ireland Statement",
                            source_email_sender="BOC Ireland <accounts@boc.ie>",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-diageo-100",
                            attachment_index=0,
                            attachment_name="diageo_9263312263.pdf",
                            supplier="Diageo",
                            document_type="invoice",
                            document_date=date(2026, 4, 2),
                            reference="9263312263",
                            amount=Decimal("3945.57"),
                            vat_amount=Decimal("590.00"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Diageo/9263312263.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Diageo invoice 9263312263",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-diageo-101",
                            attachment_index=0,
                            attachment_name="diageo_9263317044.pdf",
                            supplier="Diageo",
                            document_type="invoice",
                            document_date=date(2026, 4, 10),
                            reference="9263317044",
                            amount=Decimal("477.71"),
                            vat_amount=Decimal("71.00"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Diageo/9263317044.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Diageo invoice 9263317044",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-diageo-statement",
                            attachment_index=0,
                            attachment_name="diageo_statement.pdf",
                            supplier="Diageo",
                            document_type="statement",
                            document_date=date(2026, 4, 30),
                            reference=None,
                            amount=Decimal("5464.37"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Diageo/statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Diageo Statement",
                            source_email_sender="Diageo Ireland <accounts@diageo.ie>",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-diageo-sub-statement",
                            attachment_index=0,
                            attachment_name="diageo_sub_statement.pdf",
                            supplier="Diageo",
                            document_type="statement",
                            document_date=date(2026, 4, 2),
                            reference="TCT060",
                            amount=Decimal("762.91"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Diageo/sub_statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Diageo Sub Account Statement",
                            source_email_sender="Diageo Ireland <accounts@diageo.ie>",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-lv-100",
                            attachment_index=0,
                            attachment_name="lovell_882142.pdf",
                            supplier="Lovell Bros. Ltd.",
                            document_type="invoice",
                            document_date=date(2026, 4, 7),
                            reference="882142",
                            amount=Decimal("9.95"),
                            vat_amount=Decimal("1.86"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Lovell/882142.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Lovell invoice 882142",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-lv-101",
                            attachment_index=0,
                            attachment_name="lovell_882570.pdf",
                            supplier="Lovell Bros. Ltd.",
                            document_type="invoice",
                            document_date=date(2026, 4, 9),
                            reference="882570",
                            amount=Decimal("12.56"),
                            vat_amount=Decimal("2.35"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Lovell/882570.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Lovell invoice 882570",
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=2,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 27),
                            description1="MOODMASTER",
                            description2=None,
                            debit_amount=Decimal("98.40"),
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
                            row_number=3,
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
                            row_number=4,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 7),
                            description1="D/D Radius Busines",
                            description2="IE26040246051352",
                            debit_amount=Decimal("22.51"),
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
                            row_number=5,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 2),
                            description1="D/D DIAGEO IRELAND",
                            description2="IE26040245760718",
                            debit_amount=Decimal("4263.76"),
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

                report = await build_reconciliation_report(
                    db=session,
                    user_id=self.user.id,
                    month="2026-04",
                    source_type="bank_statement",
                    limit=10,
                    annotated_only=False,
                )

            moodmaster_item = next(item for item in report.transactions if item.row_number == 2)
            self.assertEqual(moodmaster_item.status, "suggested")
            self.assertEqual(
                [match.reference for match in moodmaster_item.suggested_matches],
                ["112020"],
            )

            connacht_item = next(item for item in report.transactions if item.row_number == 3)
            self.assertEqual(connacht_item.status, "unmatched")
            self.assertEqual(connacht_item.suggested_matches, [])
            self.assertEqual(
                [match.document_type for match in connacht_item.supporting_matches],
                ["statement"],
            )
            self.assertEqual(connacht_item.supporting_matches[0].supplier, "Connacht Bottlers")
            self.assertIsNotNone(connacht_item.analysis_note)

            radius_item = next(item for item in report.transactions if item.row_number == 4)
            self.assertEqual(radius_item.status, "unmatched")
            self.assertEqual(radius_item.suggested_matches, [])

            diageo_item = next(item for item in report.transactions if item.row_number == 5)
            self.assertEqual(diageo_item.status, "suggested")
            self.assertEqual(diageo_item.suggested_matches, [])
            self.assertEqual(
                [match.document_type for match in diageo_item.supporting_matches],
                ["statement", "statement"],
            )
            self.assertIsNotNone(diageo_item.analysis_note)
            self.assertIn("likely account/statement settlement", diageo_item.analysis_note)


if __name__ == "__main__":
    unittest.main()
