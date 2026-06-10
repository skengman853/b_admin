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
    from app.services.document_ledger import build_document_ledgers  # noqa: E402
    from app.services.transaction_reconciliation import (  # noqa: E402
        AUTO_EXACT_LINK_NOTE,
        build_transaction_reconciliation_flow,
        build_reconciliation_report,
        build_transaction_reconciliation_item,
        load_candidate_documents_for_transaction,
        load_supporting_documents_for_transaction,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class TransactionReconciliationTests(unittest.TestCase):
        @unittest.skip(f"transaction reconciliation tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    DIAGEO_STATEMENT_TEXT = """STATEMENT
Page No.
Date
Currency

Account No.
Payment Terms

314773
Invoice +7days -2.5%Settlement

Statement Address

Correspondence Address

CAREY'S BAR LIMITED
T/A CAREY'S BAR
38 MARDYKE STREET
ATHLONE N37 AP95

Doc
Date

Billing
Doc

Txn
Type

Customer
Reference

Due
Date

Clearing
Doc

Opening Balance @ 01.04.2026
02.04.2026
07.04.2026
10.04.2026
15.04.2026
16.04.2026
21.04.2026
23.04.2026
28.04.2026

Contact Name:
Contact No.:

9263312263
2503715694
9263317044
2503719806
9263321673
2503722026
9263326661
2503726062

INVOIC
PAYMNT
INVOIC
PAYMNT
INVOIC
PAYMNT
INVOIC
PAYMNT

09.04.2026
07.04.2026
17.04.2026
15.04.2026
23.04.2026
21.04.2026
30.04.2026
28.04.2026

Total Due
0.00

Total Sett Disc
275.17-
"""

    BULMERS_ACCOUNT_STATEMENT_TEXT = """Customer Statement,1001,,,,31/12/16,113480.60

STATEMENT

Issued by
Bulmers Ireland

CAREY'S BAR LTD
T/A CAREY'S
38 MARDYKE STREET
ATHLONE
Ireland

Customer Number
69000795

Statement Date
30/04/26
Page 1 of 1

Item
Date
Due
Date
TRN
Document
No
25/03/26
31/03/26
02/04/26
15/04/26
15/04/26
30/04/26
01/04/26
07/04/26
09/04/26
22/04/26
22/04/26
07/05/26
INV
INV
INV
INV
INV
INV
4100706
4112987
4120677
4150604
4150707
4188699
Current €
851.87
Item
Amount
876.10
18.00
939.96
1112.45
18.00
851.87
Payment method: Direct Debit
"""

    DIAGEO_SUB_STATEMENT_TEXT = """SUB ACCOUNT STATEMENT

Document Date
02.04.2026
01.03.2026 - 31.03.2026

Invoice Address
314773
CAREY'S BAR LIMITED
T/A CAREY'S BAR
38 MARDYKE STREET

Closing Balance EUR

-5,464.37
"""

    CONNACHT_STATEMENT_TEXT = """JJ Mahon and Sons (Connacht) Ltd
T/A CONNACHT BOTTLERS Grange Carrick-On-Shannon Co. Leitrim,
STATEMENT
CAREYS BAR LTD
CAREYS
38 MARYDYKE STREET
ATHLONE
Co. Westmeath N37 AP95
Date:
30/04/2026
Account No.:
CAREY01
22/04/2026
34508
37847
Invoice
740.98
740.98
28/04/2026
34769
38177
Invoice
786.50
1,527.48
29/04/2026
DD-29-04
April
786.50
Receipt
Balance
To Pay Directly into Bank Name: Connacht Bottlers.
"""

    CONNACHT_MESSY_STATEMENT_TEXT = """JJ Mahon and Sons (Connacht) Ltd
T/A CONNACHT BOTTLERS Grange Carrick-On-Shannon Co. Leitrim,
Phone: (071) 967 1793 Fax: (071) 967 1793
Vat Reg No.: IE4110224AH
email : info@connachtbottlers.ie
www : www.jjmahons.com

STATEMENT

CAREYS BAR LTD
CAREYS
38 MARYDYKE STREET
ATHLONE
Co. Westmeath N37 AP95

Date

Reference

Your Ref

Order No.

Type

Date:

30/04/2026

Account No.:

CAREY01

Debit

B/FWD

Credit

350.33

350.33

01/04/2026

DD-01-04

01/04/2026

33655

08/04/2026

DD-08-04

08/04/2026

33941

09/04/2026

34036

15/04/2026

DD-15-04

15/04/2026

34222

16/04/2026

DD-16-04

Receipt

169.74

850.11

22/04/2026

DD-22-04

Receipt

850.11

0.00

22/04/2026

34508

37847

Invoice

740.98

740.98

28/04/2026

34769

38177

Invoice

786.50

1,527.48

29/04/2026

DD-29-04

April
786.50

Receipt

Balance

36899

350.33

Invoice

1,037.02

Receipt

DEL BY REP

Invoice

1,116.49

1,116.49

37374

Invoice

169.74

1,286.23
1,116.49

Invoice

850.11

Receipt

0.00

0.00

0.00

37275

37537

February

1,037.02
1,037.02

Receipt

March

0.00

January
0.00

1,019.85

740.98

December+
0.00

169.74

786.50

BALANCE
786.50

To Pay Directly into Bank Name: Connacht Bottlers. Account: 43232127 Bank: BANK OF IRELAND, Main Street, Kildare. Sort Code:
90-11-67 IBAN: IE36BOFI90116743232127 BIC: BOFIIE2D
"""

    class TransactionReconciliationTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="reconcile@example.com", password_hash="hashed")
                self.connacht_careys_statement_id = uuid.uuid4()
                self.connacht_canal_statement_id = uuid.uuid4()
                self.connacht_careys_credit_id = uuid.uuid4()
                self.connacht_canal_credit_id = uuid.uuid4()
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
            self.assertEqual(matched_item.resolution_bucket, "confirm_match")
            self.assertEqual(matched_item.recommended_review_status, "linked")

            partial_item = next(item for item in report.transactions if item.row_number == 11)
            self.assertEqual(partial_item.status, "partial")
            self.assertEqual([match.reference for match in partial_item.exact_matches], ["PX200"])
            self.assertEqual(partial_item.resolution_bucket, "complete_partial_match")
            self.assertIsNone(partial_item.recommended_review_status)

            single_suggested_item = next(item for item in report.transactions if item.row_number == 12)
            self.assertEqual(single_suggested_item.status, "suggested")
            self.assertEqual([match.reference for match in single_suggested_item.suggested_matches], ["SG300"])
            self.assertEqual(single_suggested_item.resolution_bucket, "confirm_match")
            self.assertEqual(single_suggested_item.recommended_review_status, "linked")

            grouped_item = next(item for item in report.transactions if item.row_number == 13)
            self.assertEqual(grouped_item.status, "suggested")
            self.assertEqual(
                {match.reference for match in grouped_item.suggested_matches},
                {"GR400", "GR401"},
            )
            self.assertEqual(grouped_item.resolution_bucket, "confirm_match")
            self.assertEqual(grouped_item.recommended_review_status, "linked")

            unmatched_item = next(item for item in report.transactions if item.row_number == 14)
            self.assertEqual(unmatched_item.resolution_bucket, "awaiting_document")
            self.assertEqual(unmatched_item.recommended_review_status, "awaiting_document")

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
                            source_email_sender="local-archive",
                            extracted_text=(
                                "Invoice ##EMAIL bridgetcareysbar@gmail.com##\n\n"
                                "##VAR1 CAR18##\n\n"
                                "Careys Tavern Invoice No: 111769\n"
                                "38 Mardyke Street\n\n"
                                "Invoice Date: 03/04/2026\n\n"
                                "Athlone\n"
                                "Co Westmeath\n\n"
                                "Account No: CAR18\n"
                            ),
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-aa-101",
                            attachment_index=0,
                            attachment_name="automatic_amusements_111539.pdf",
                            supplier="Automatic Amusements",
                            document_type="invoice",
                            document_date=date(2026, 3, 3),
                            reference="111539",
                            amount=Decimal("98.40"),
                            vat_amount=Decimal("18.40"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Automatic Amusements/111539.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Automatic Amusements invoice 111539",
                            source_email_sender="local-archive",
                            extracted_text=(
                                "Invoice ##EMAIL bridgetcareysbar@gmail.com##\n\n"
                                "##VAR1 CAN02##\n\n"
                                "Canal Turn Invoice No: 111539\n"
                                "Main Street\n\n"
                                "Invoice Date: 03/03/2026\n\n"
                                "Ballymahon\n"
                                "Co Longford\n\n"
                                "Account No: CAN02\n"
                            ),
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
                            id=self.connacht_careys_statement_id,
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
                            extracted_text=(
                                "JJ Mahon and Sons (Connacht) Ltd\n"
                                "CAREYS BAR LTD\n"
                                "CAREYS TAVERN\n"
                                "38 MARDYKE STREET\n"
                                "ATHLONE\n"
                                "WESTMEATH N37 AP95\n"
                            ),
                        ),
                        Document(
                            id=self.connacht_canal_statement_id,
                            user_id=self.user.id,
                            gmail_message_id="doc-cb-statement-canal",
                            attachment_index=0,
                            attachment_name="CANAL01-Statement.pdf",
                            supplier="Connacht Bottlers",
                            document_type="statement",
                            document_date=date(2026, 4, 30),
                            reference=None,
                            amount=Decimal("1144.42"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Connacht Bottlers/canal_statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Connacht Bottlers Canal Statement",
                            source_email_sender="Info - Connacht Bottlers <info@connachtbottlers.ie>",
                            extracted_text=(
                                "JJ Mahon and Sons (Connacht) Ltd\n"
                                "CAREYS BAR LTD\n"
                                "CANAL TURN\n"
                                "MAIN STREET\n"
                                "BALLYMAHON\n"
                                "LONGFORD N39 WR64\n"
                            ),
                        ),
                        Document(
                            id=self.connacht_careys_credit_id,
                            user_id=self.user.id,
                            gmail_message_id="doc-cb-credit-careys",
                            attachment_index=0,
                            attachment_name="CAREY01-35241.pdf",
                            supplier="Connacht Bottlers",
                            document_type="credit_note",
                            document_date=date(2026, 5, 6),
                            reference="35241",
                            amount=Decimal("55.42"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Connacht Bottlers/careys_credit_note.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Connacht Bottlers Invoices/Credits 06/05/2026",
                            source_email_sender="Info - Connacht Bottlers <info@connachtbottlers.ie>",
                            extracted_text=(
                                "JJ Mahon and Sons (Connacht) Ltd\n"
                                "CREDIT NOTE\n"
                                "Billing address: Delivery address:\n"
                                "CAREYS BAR LTD CAREYS\n"
                                "T/A CAREYS 38 MARYDYKE STREET\n"
                                "ATHLONE Co. Westmeath N37 AP95\n"
                                "35241 06/05/2026 CAREY01\n"
                            ),
                        ),
                        Document(
                            id=self.connacht_canal_credit_id,
                            user_id=self.user.id,
                            gmail_message_id="doc-cb-credit-canal",
                            attachment_index=0,
                            attachment_name="CANA01-35161.pdf",
                            supplier="Connacht Bottlers",
                            document_type="credit_note",
                            document_date=date(2026, 5, 5),
                            reference="35161",
                            amount=Decimal("24.60"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Connacht Bottlers/canal_credit_note.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Connacht Bottlers Invoices/Credits 05/05/2026",
                            source_email_sender="Info - Connacht Bottlers <info@connachtbottlers.ie>",
                            extracted_text=(
                                "JJ Mahon and Sons (Connacht) Ltd\n"
                                "CREDIT NOTE\n"
                                "Billing address: Delivery address:\n"
                                "CAREYS BAR LTD CANAL TURN\n"
                                "T/A CANAL TURN MAIN STREET\n"
                                "BALLYMAHON LONGFORD N39 WR64\n"
                                "35161 05/05/2026 CANA01\n"
                            ),
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-bulmers-careys-statement",
                            attachment_index=0,
                            attachment_name="bulmers_careys_statement.pdf",
                            supplier="Bulmers",
                            document_type="statement",
                            document_date=date(2026, 4, 29),
                            reference=None,
                            amount=Decimal("876.10"),
                            vat_amount=None,
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Bulmers/careys_statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Bulmers Careys Statement",
                            source_email_sender="Bulmers <accounts@bulmers.ie>",
                            extracted_text=(
                                "STATEMENT\n"
                                "Careys Tavern\n"
                                "38 Mardyke Street\n"
                                "Athlone\n"
                                "Account No: CAR18\n"
                            ),
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
                            extracted_text=DIAGEO_STATEMENT_TEXT,
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
                            extracted_text=DIAGEO_SUB_STATEMENT_TEXT,
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
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-he-careys",
                            attachment_index=0,
                            attachment_name="Careys Bar - heineken_194159926.pdf",
                            supplier="Heineken",
                            document_type="invoice",
                            document_date=date(2026, 4, 15),
                            reference="194159926",
                            amount=Decimal("2636.35"),
                            vat_amount=Decimal("493.15"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Heineken/Careys/heineken_194159926.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Heineken/Careys Bar/Invoices/heineken_194159926.pdf",
                            source_email_sender="local-archive",
                            extracted_text=(
                                "Invoice to:\n"
                                "Careys Pub\n"
                                "Maye Carey\n"
                                "Careys Bar Limited\n"
                                "38 Mardyke Street\n"
                            ),
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-he-canal",
                            attachment_index=0,
                            attachment_name="Canal Turn - heineken_194149047.pdf",
                            supplier="Heineken",
                            document_type="invoice",
                            document_date=date(2026, 4, 7),
                            reference="194149047",
                            amount=Decimal("2636.35"),
                            vat_amount=Decimal("493.15"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Heineken/Canal/heineken_194149047.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Heineken/Canal Turn/Invoices/heineken_194149047.pdf",
                            source_email_sender="local-archive",
                            extracted_text=(
                                "Invoice to:\n"
                                "The Canal Turn\n"
                                "Careys Bar Limited\n"
                                "Careys Bar Limited\n"
                            ),
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=7,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 1),
                            description1="D/D M AND J GLEESO",
                            description2="IE26033042208111",
                            debit_amount=Decimal("876.10"),
                            transaction_type="Debit",
                            category=None,
                            annotation_types=[],
                            annotation_notes=[],
                            has_linked_annotation=False,
                            expected_supplier="Bulmers",
                            raw_row_json={},
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
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=6,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 20),
                            description1="D/D HEINEKEN IRELAND",
                            description2="IE26042012345678",
                            debit_amount=Decimal("2636.35"),
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
            self.assertIn(
                "Document venue aligns with the transaction pub",
                moodmaster_item.suggested_matches[0].reason,
            )
            self.assertEqual(moodmaster_item.resolution_bucket, "confirm_match")
            self.assertEqual(moodmaster_item.recommended_review_status, "linked")

            connacht_item = next(item for item in report.transactions if item.row_number == 3)
            self.assertEqual(connacht_item.status, "unmatched")
            self.assertEqual(connacht_item.suggested_matches, [])
            self.assertEqual(
                {match.document_type for match in connacht_item.supporting_matches},
                {"statement", "credit_note"},
            )
            self.assertEqual(
                {match.document_id for match in connacht_item.supporting_matches},
                {self.connacht_careys_statement_id, self.connacht_careys_credit_id},
            )
            self.assertIsNotNone(connacht_item.analysis_note)
            self.assertEqual(connacht_item.resolution_bucket, "review_supporting_docs")
            self.assertEqual(connacht_item.recommended_review_status, "supporting_docs_only")

            radius_item = next(item for item in report.transactions if item.row_number == 4)
            self.assertEqual(radius_item.status, "unmatched")
            self.assertEqual(radius_item.suggested_matches, [])
            self.assertEqual(radius_item.resolution_bucket, "awaiting_document")
            self.assertEqual(radius_item.recommended_review_status, "awaiting_document")

            diageo_item = next(item for item in report.transactions if item.row_number == 5)
            self.assertEqual(diageo_item.status, "suggested")
            self.assertEqual(diageo_item.suggested_matches, [])
            self.assertEqual(
                [match.document_type for match in diageo_item.supporting_matches],
                ["statement", "statement"],
            )
            self.assertIsNotNone(diageo_item.analysis_note)
            self.assertIn("financial statement document(s)", diageo_item.analysis_note)
            self.assertIn("invoice reference(s)", diageo_item.analysis_note)
            self.assertIn("likely account/statement settlement", diageo_item.analysis_note)
            self.assertEqual(diageo_item.resolution_bucket, "review_supporting_docs")
            self.assertEqual(diageo_item.recommended_review_status, "supporting_docs_only")

            heineken_item = next(item for item in report.transactions if item.row_number == 6)
            self.assertEqual(heineken_item.status, "suggested")
            self.assertEqual(
                [match.reference for match in heineken_item.suggested_matches],
                ["194159926"],
            )
            self.assertIn(
                "Document venue aligns with the transaction pub",
                heineken_item.suggested_matches[0].reason,
            )

            gleeson_hint_item = next(item for item in report.transactions if item.row_number == 7)
            self.assertEqual(
                [match.supplier for match in gleeson_hint_item.supporting_matches],
                ["Bulmers"],
            )
            self.assertEqual(gleeson_hint_item.supporting_matches[0].document_type, "statement")

        async def test_statement_invoice_refs_break_ties_between_same_amount_invoices(self) -> None:
            async with self.session_factory() as session:
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-bulmers-statement-lines",
                            attachment_index=0,
                            attachment_name="bulmers_statement.pdf",
                            supplier="Bulmers",
                            document_type="statement",
                            document_date=date(2026, 4, 30),
                            amount=Decimal("0.00"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Bulmers/statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Bulmers Careys Statement",
                            source_email_sender="Bulmers <accounts@bulmers.ie>",
                            extracted_text=BULMERS_ACCOUNT_STATEMENT_TEXT,
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-bulmers-mar-invoice",
                            attachment_index=0,
                            attachment_name="Careys Bar - Bulmers Ireland - Inv 099 - 4112987 - Date 25-03-2026.pdf",
                            supplier="Bulmers",
                            document_type="invoice",
                            document_date=date(2026, 3, 25),
                            reference="4112987",
                            amount=Decimal("18.00"),
                            vat_amount=Decimal("0.00"),
                            confidence_score=0.8,
                            extraction_status="review",
                            local_path="Documents/Bulmers/4112987.pdf",
                            needs_review=True,
                            review_reasons=["suspicious_amounts"],
                            source_email_subject="Bulmers Ireland/Invoices/Careys Bar/Bulmers Ireland - Inv 099 - 4112987 - Date 25-03-2026.pdf",
                            source_email_sender="local-archive",
                            extracted_text="Invoice Number 4112987 Total € 18.00",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-bulmers-apr-invoice",
                            attachment_index=0,
                            attachment_name="Careys Bar - Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026.pdf",
                            supplier="Bulmers",
                            document_type="invoice",
                            document_date=date(2026, 4, 15),
                            reference="4150707",
                            amount=Decimal("18.00"),
                            vat_amount=Decimal("0.00"),
                            confidence_score=0.8,
                            extraction_status="review",
                            local_path="Documents/Bulmers/4150707.pdf",
                            needs_review=True,
                            review_reasons=["suspicious_amounts"],
                            source_email_subject="Bulmers Ireland/Invoices/Careys Bar/Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026.pdf",
                            source_email_sender="local-archive",
                            extracted_text="Invoice Number 4150707 Total € 18.00",
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=202,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 7),
                            description1="D/D M AND J GLEESO",
                            description2="IE26040145489598",
                            debit_amount=Decimal("18.00"),
                            transaction_type="Debit",
                            category=None,
                            annotation_types=[],
                            annotation_notes=[],
                            has_linked_annotation=False,
                            expected_supplier="Bulmers",
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
                    annotated_only=False,
                    limit=20,
                )

            item = next(entry for entry in report.transactions if entry.row_number == 202)
            self.assertEqual(item.status, "suggested")
            self.assertEqual([match.reference for match in item.suggested_matches[:2]], ["4112987", "4150707"])
            self.assertIn("Supporting statement references this invoice", item.suggested_matches[0].reason)
            self.assertIn("Statement due date matches the bank transaction date", item.suggested_matches[0].reason)
            self.assertIn("Invoice date is after the bank transaction", item.suggested_matches[1].reason)

        async def test_confirmed_persisted_invoice_link_is_primary_component_context(self) -> None:
            async with self.session_factory() as session:
                statement = Document(
                    user_id=self.user.id,
                    gmail_message_id="doc-bulmers-statement-flow",
                    attachment_index=0,
                    attachment_name="bulmers_statement.pdf",
                    supplier="Bulmers",
                    document_type="statement",
                    document_date=date(2026, 4, 30),
                    amount=Decimal("0.00"),
                    confidence_score=0.99,
                    extraction_status="extracted",
                    local_path="Documents/Bulmers/statement.pdf",
                    needs_review=False,
                    review_reasons=[],
                    source_email_subject="Bulmers Careys Statement",
                    source_email_sender="Bulmers <accounts@bulmers.ie>",
                    extracted_text=BULMERS_ACCOUNT_STATEMENT_TEXT,
                )
                march_invoice = Document(
                    user_id=self.user.id,
                    gmail_message_id="doc-bulmers-mar-flow",
                    attachment_index=0,
                    attachment_name="Careys Bar - Bulmers Ireland - Inv 099 - 4112987 - Date 25-03-2026.pdf",
                    supplier="Bulmers",
                    document_type="invoice",
                    document_date=date(2026, 3, 25),
                    reference="4112987",
                    amount=Decimal("18.00"),
                    vat_amount=Decimal("0.00"),
                    confidence_score=0.8,
                    extraction_status="review",
                    local_path="Documents/Bulmers/4112987.pdf",
                    needs_review=True,
                    review_reasons=["suspicious_amounts"],
                    source_email_subject="Bulmers Ireland/Invoices/Careys Bar/Bulmers Ireland - Inv 099 - 4112987 - Date 25-03-2026.pdf",
                    source_email_sender="local-archive",
                    extracted_text="Invoice Number 4112987 Total € 18.00",
                )
                april_invoice = Document(
                    user_id=self.user.id,
                    gmail_message_id="doc-bulmers-apr-flow",
                    attachment_index=0,
                    attachment_name="Careys Bar - Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026.pdf",
                    supplier="Bulmers",
                    document_type="invoice",
                    document_date=date(2026, 4, 15),
                    reference="4150707",
                    amount=Decimal("18.00"),
                    vat_amount=Decimal("0.00"),
                    confidence_score=0.8,
                    extraction_status="review",
                    local_path="Documents/Bulmers/4150707.pdf",
                    needs_review=True,
                    review_reasons=["suspicious_amounts"],
                    source_email_subject="Bulmers Ireland/Invoices/Careys Bar/Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026.pdf",
                    source_email_sender="local-archive",
                    extracted_text="Invoice Number 4150707 Total € 18.00",
                )
                transaction = Transaction(
                    user_id=self.user.id,
                    source_type="bank_statement",
                    source_file="bankstatements/sample.pdf",
                    source_sheet="53747-031",
                    row_number=203,
                    posted_account="93-22-64 - 53747-031",
                    pub="Careys",
                    transaction_date=date(2026, 4, 7),
                    description1="D/D M AND J GLEESO",
                    description2="IE26040145489598",
                    debit_amount=Decimal("18.00"),
                    transaction_type="Debit",
                    category=None,
                    annotation_types=[],
                    annotation_notes=[],
                    has_linked_annotation=False,
                    expected_supplier="Bulmers",
                    raw_row_json={},
                )
                session.add_all([statement, march_invoice, april_invoice, transaction])
                await session.flush()

                persisted_link = TransactionDocumentLink(
                    user_id=self.user.id,
                    transaction_id=transaction.id,
                    document_id=march_invoice.id,
                    role="invoice",
                    status="confirmed",
                    score=1.0,
                    match_reason="Confirmed invoice link",
                )
                persisted_link.document = march_invoice

                invoice_docs = [march_invoice, april_invoice]
                support_docs = [statement]
                invoice_ledgers = build_document_ledgers(invoice_docs)
                support_ledgers = build_document_ledgers(support_docs)
                analysis = build_transaction_reconciliation_item(
                    transaction=transaction,
                    documents=invoice_docs,
                    supporting_documents=support_docs,
                    document_ledgers=invoice_ledgers,
                    supporting_document_ledgers=support_ledgers,
                )
                flow = build_transaction_reconciliation_flow(
                    transaction=transaction,
                    analysis=analysis,
                    invoice_documents=invoice_docs,
                    supporting_documents=support_docs,
                    invoice_ledgers=invoice_ledgers,
                    supporting_ledgers=support_ledgers,
                    persisted_links=[persisted_link],
                )

            component_stage = next(stage for stage in flow.stages if stage.key == "components")
            self.assertEqual(component_stage.documents[0].reference, "4112987")

        async def test_connacht_statement_line_amount_can_drive_support_analysis(self) -> None:
            async with self.session_factory() as session:
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-cb-statement-line-match",
                            attachment_index=0,
                            attachment_name="CAREY01-Statement.pdf",
                            supplier="Connacht Bottlers",
                            document_type="statement",
                            document_date=date(2026, 4, 30),
                            amount=Decimal("1527.48"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Connacht Bottlers/statement_line_match.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Connacht Bottlers Statement",
                            source_email_sender="Info - Connacht Bottlers <info@connachtbottlers.ie>",
                            extracted_text=CONNACHT_STATEMENT_TEXT,
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=101,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 29),
                            description1="D/D CONNACHT BOTTL",
                            description2="IE26042912220659",
                            debit_amount=Decimal("786.50"),
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
                    limit=20,
                    annotated_only=False,
                )

            connacht_item = next(item for item in report.transactions if item.row_number == 101)
            self.assertEqual(connacht_item.status, "suggested")
            self.assertEqual(connacht_item.suggested_matches, [])
            self.assertEqual(
                [match.document_type for match in connacht_item.supporting_matches],
                ["statement"],
            )
            self.assertIsNotNone(connacht_item.analysis_note)
            self.assertIn("matching the bank amount 786.50", connacht_item.analysis_note)
            self.assertIn("DD-29-04", connacht_item.analysis_note)
            self.assertEqual(connacht_item.resolution_bucket, "review_supporting_docs")

        async def test_statement_period_is_preferred_over_document_date_for_supporting_docs(self) -> None:
            async with self.session_factory() as session:
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-heineken-march-statement",
                            attachment_index=0,
                            attachment_name="heineken_march_statement.pdf",
                            supplier="Heineken",
                            document_type="statement",
                            document_date=date(2026, 4, 2),
                            amount=Decimal("0.00"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Heineken/march_statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Heineken Statement March",
                            source_email_sender="Heineken <accounts@heineken.ie>",
                            extracted_text="STATEMENT 01/03/26 31/03/26",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-heineken-april-statement",
                            attachment_index=0,
                            attachment_name="heineken_april_statement.pdf",
                            supplier="Heineken",
                            document_type="statement",
                            document_date=date(2026, 5, 3),
                            amount=Decimal("0.00"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Heineken/april_statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Heineken Statement April",
                            source_email_sender="Heineken <accounts@heineken.ie>",
                            extracted_text="STATEMENT 01/04/26 30/04/26",
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=401,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 23),
                            description1="D/D HEINEKEN IRELA",
                            description2="IE26042300000000",
                            debit_amount=Decimal("3198.25"),
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
                    limit=20,
                    annotated_only=False,
                )

            item = next(entry for entry in report.transactions if entry.row_number == 401)
            self.assertEqual(item.resolution_bucket, "review_supporting_docs")
            self.assertGreaterEqual(len(item.supporting_matches), 2)
            self.assertEqual(item.supporting_matches[0].document_date, date(2026, 5, 3))
            self.assertIn(
                "Statement period 2026-04-01 to 2026-04-30 covers the bank transaction date",
                item.supporting_matches[0].reason,
            )

        async def test_confirm_match_flow_hides_unrelated_statement_periods(self) -> None:
            async with self.session_factory() as session:
                transaction = Transaction(
                    user_id=self.user.id,
                    source_type="bank_statement",
                    source_file="bankstatements/sample.pdf",
                    source_sheet="53747-031",
                    row_number=402,
                    posted_account="93-22-64 - 53747-031",
                    pub="Careys",
                    transaction_date=date(2026, 4, 7),
                    description1="D/D HEINEKEN IRELA",
                    description2="IE26040700000000",
                    debit_amount=Decimal("4196.91"),
                    transaction_type="Debit",
                    category=None,
                    annotation_types=[],
                    annotation_notes=[],
                    has_linked_annotation=False,
                    raw_row_json={},
                )
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-heineken-march-statement-flow",
                            attachment_index=0,
                            attachment_name="heineken_march_statement.pdf",
                            supplier="Heineken",
                            document_type="statement",
                            document_date=date(2026, 4, 2),
                            reference="Summary",
                            amount=Decimal("4217.21"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Heineken/march_statement.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Heineken Statement March",
                            source_email_sender="Heineken <accounts@heineken.ie>",
                            extracted_text=(
                                "STATEMENT OF ACCOUNT\n"
                                "01/03/26\n31/03/26\n"
                                "Item\nDate\n"
                                "INV\n194101304\n01/03/26\n07/03/26\n"
                                "Payment\n2000025959\n30/03/26\n30/03/26\n"
                                "Item\nAmount\n4217.21\n4217.21\n"
                            ),
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-heineken-april-invoice-flow",
                            attachment_index=0,
                            attachment_name="heineken_194141091.pdf",
                            supplier="Heineken",
                            document_type="invoice",
                            document_date=date(2026, 4, 1),
                            reference="194141091",
                            amount=Decimal("4196.91"),
                            vat_amount=Decimal("0.00"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Heineken/Careys/heineken_194141091.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Heineken/Careys/heineken_194141091.pdf",
                            source_email_sender="local-archive",
                            extracted_text="Invoice Number 194141091 Total € 4196.91",
                        ),
                        transaction,
                    ]
                )
                await session.commit()

                candidate_documents = await load_candidate_documents_for_transaction(
                    db=session,
                    user_id=self.user.id,
                    transaction=transaction,
                )
                supporting_documents = await load_supporting_documents_for_transaction(
                    db=session,
                    user_id=self.user.id,
                    transaction=transaction,
                )
                candidate_ledgers = build_document_ledgers(candidate_documents)
                supporting_ledgers = build_document_ledgers(supporting_documents)
                analysis = build_transaction_reconciliation_item(
                    transaction=transaction,
                    documents=candidate_documents,
                    supporting_documents=supporting_documents,
                    document_ledgers=candidate_ledgers,
                    supporting_document_ledgers=supporting_ledgers,
                )
                flow = build_transaction_reconciliation_flow(
                    transaction=transaction,
                    analysis=analysis,
                    invoice_documents=candidate_documents,
                    supporting_documents=supporting_documents,
                    invoice_ledgers=candidate_ledgers,
                    supporting_ledgers=supporting_ledgers,
                    persisted_links=[],
                )

            self.assertEqual(analysis.resolution_bucket, "confirm_match")
            self.assertEqual([match.reference for match in analysis.suggested_matches], ["194141091"])
            statement_stage = next(stage for stage in flow.stages if stage.key == "statement")
            self.assertEqual(statement_stage.documents, [])

        async def test_confirm_match_flow_keeps_closest_statement_as_context_when_unparsed(self) -> None:
            async with self.session_factory() as session:
                transaction = Transaction(
                    user_id=self.user.id,
                    source_type="bank_statement",
                    source_file="bankstatements/sample.pdf",
                    source_sheet="53747-031",
                    row_number=403,
                    posted_account="93-22-64 - 53747-031",
                    pub="Careys",
                    transaction_date=date(2026, 4, 1),
                    description1="D/D M AND J GLEESO",
                    description2="IE26040145489598",
                    debit_amount=Decimal("876.10"),
                    transaction_type="Debit",
                    category=None,
                    annotation_types=[],
                    annotation_notes=[],
                    has_linked_annotation=False,
                    raw_row_json={},
                    expected_supplier="Bulmers ireland",
                )
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-bulmers-context-statement",
                            attachment_index=0,
                            attachment_name="bulmers_stmt_017.pdf",
                            supplier="Bulmers",
                            document_type="statement",
                            document_date=date(2026, 3, 31),
                            reference="Stmt 017",
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Bulmers/careys_stmt_017.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Bulmers Ireland/Statements/Careys Bar/Bulmers Ireland - Stmt 017 - Date 31-03-2026 - Linked.pdf",
                            source_email_sender="local-archive",
                            extracted_text="Statement of account\nCareys Bar\n31/03/2026\n",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-bulmers-context-invoice",
                            attachment_index=0,
                            attachment_name="bulmers_4100706.pdf",
                            supplier="Bulmers",
                            document_type="invoice",
                            document_date=date(2026, 3, 25),
                            reference="4100706",
                            amount=Decimal("876.10"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Bulmers/Careys/bulmers_4100706.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Bulmers/Careys/bulmers_4100706.pdf",
                            source_email_sender="local-archive",
                            extracted_text="Invoice Number 4100706 Total € 876.10",
                        ),
                        transaction,
                    ]
                )
                await session.commit()

                candidate_documents = await load_candidate_documents_for_transaction(
                    db=session,
                    user_id=self.user.id,
                    transaction=transaction,
                )
                supporting_documents = await load_supporting_documents_for_transaction(
                    db=session,
                    user_id=self.user.id,
                    transaction=transaction,
                )
                candidate_ledgers = build_document_ledgers(candidate_documents)
                supporting_ledgers = build_document_ledgers(supporting_documents)
                analysis = build_transaction_reconciliation_item(
                    transaction=transaction,
                    documents=candidate_documents,
                    supporting_documents=supporting_documents,
                    document_ledgers=candidate_ledgers,
                    supporting_document_ledgers=supporting_ledgers,
                )
                flow = build_transaction_reconciliation_flow(
                    transaction=transaction,
                    analysis=analysis,
                    invoice_documents=candidate_documents,
                    supporting_documents=supporting_documents,
                    invoice_ledgers=candidate_ledgers,
                    supporting_ledgers=supporting_ledgers,
                    persisted_links=[],
                )

            self.assertEqual(analysis.resolution_bucket, "confirm_match")
            self.assertEqual([match.reference for match in analysis.suggested_matches], ["4100706"])
            statement_stage = next(stage for stage in flow.stages if stage.key == "statement")
            self.assertEqual(len(statement_stage.documents), 1)
            self.assertEqual(statement_stage.documents[0].reference, "Stmt 017")

        async def test_flow_components_include_persisted_invoice_link_when_statement_ref_has_leading_zero(self) -> None:
            async with self.session_factory() as session:
                transaction = Transaction(
                    user_id=self.user.id,
                    source_type="bank_statement",
                    source_file="bankstatements/sample.pdf",
                    source_sheet="53747-031",
                    row_number=404,
                    posted_account="93-22-64 - 53747-031",
                    pub="Careys",
                    transaction_date=date(2026, 4, 2),
                    description1="D/D HEINEKEN IRELA",
                    description2="IE26040200000000",
                    debit_amount=Decimal("4196.91"),
                    transaction_type="Debit",
                    category=None,
                    annotation_types=[],
                    annotation_notes=[],
                    has_linked_annotation=False,
                    raw_row_json={},
                )
                statement = Document(
                    user_id=self.user.id,
                    gmail_message_id="doc-heineken-april-statement-leading-zero",
                    attachment_index=0,
                    attachment_name="heineken_april_statement.pdf",
                    supplier="Heineken",
                    document_type="statement",
                    document_date=date(2026, 5, 5),
                    reference="Summary",
                    confidence_score=0.99,
                    extraction_status="extracted",
                    local_path="Documents/Heineken/april_statement.pdf",
                    needs_review=False,
                    review_reasons=[],
                    source_email_subject="Heineken Statement April",
                    source_email_sender="Heineken <accounts@heineken.ie>",
                    extracted_text=(
                        "STATEMENT OF ACCOUNT\n\n"
                        "Careys Bar Limited\n"
                        "Date: 05.05.2026\n"
                        "Please find below your account statement with all items between 01.04.2026 To 30.04.2026:\n"
                        "Reference\nNumber\nDocument\nNumber\nDocument\nType\nDocument\nDate\nDue\nDate\nOriginal\nAmount\nResidual\nB/F\nAdjusted\nAmount\nBalance\n"
                        "1800067344\n\n"
                        "0194141091 Invoice\n\n"
                        "01.04.2026\n\n"
                        "01.04.2026\n\n"
                        "4,196.91\n\n"
                        "0.00\n\n"
                        "-4,196.91\n\n"
                        "0.00\n\n"
                        "2000030001\n\n"
                        "Payment\n\n"
                        "02.04.2026\n\n"
                        "02.04.2026\n\n"
                        "-4,196.91\n\n"
                        "0.00\n\n"
                        "4,196.91\n\n"
                        "0.00\n\n"
                        "Closing Balance as on 30.04.2026\n\n"
                        "0.00\n"
                    ),
                )
                invoice = Document(
                    user_id=self.user.id,
                    gmail_message_id="doc-heineken-april-invoice-persisted",
                    attachment_index=0,
                    attachment_name="heineken_194141091.pdf",
                    supplier="Heineken",
                    document_type="invoice",
                    document_date=date(2026, 4, 1),
                    reference="194141091",
                    amount=Decimal("4196.91"),
                    vat_amount=Decimal("0.00"),
                    confidence_score=0.99,
                    extraction_status="extracted",
                    local_path="Documents/Heineken/Careys/heineken_194141091.pdf",
                    needs_review=False,
                    review_reasons=[],
                    source_email_subject="Heineken/Careys/heineken_194141091.pdf",
                    source_email_sender="local-archive",
                    extracted_text="Invoice Number 194141091 Total € 4196.91",
                )
                session.add_all([statement, invoice, transaction])
                await session.commit()

                supporting_ledgers = build_document_ledgers([statement])
                analysis = build_transaction_reconciliation_item(
                    transaction=transaction,
                    documents=[],
                    supporting_documents=[statement],
                    document_ledgers=[],
                    supporting_document_ledgers=supporting_ledgers,
                )
                persisted_link = TransactionDocumentLink(
                    user_id=self.user.id,
                    transaction_id=transaction.id,
                    document_id=invoice.id,
                    role="invoice",
                    status="confirmed",
                    score=1.0,
                    match_reason="confirmed invoice link",
                    amount_applied=Decimal("4196.91"),
                    document=invoice,
                )
                flow = build_transaction_reconciliation_flow(
                    transaction=transaction,
                    analysis=analysis,
                    invoice_documents=[],
                    supporting_documents=[statement],
                    invoice_ledgers=[],
                    supporting_ledgers=supporting_ledgers,
                    persisted_links=[persisted_link],
                )

            component_stage = next(stage for stage in flow.stages if stage.key == "components")
            self.assertEqual(component_stage.status, "ready")
            self.assertEqual([document.reference for document in component_stage.documents], ["194141091"])
            self.assertEqual(component_stage.summary, "The imported invoices and credit notes line up with the statement settlement.")
            self.assertFalse(
                any(item.startswith("Missing imported invoice refs:") for item in component_stage.items)
            )

        async def test_connacht_fuzzy_statement_amount_context_can_drive_support_analysis(self) -> None:
            async with self.session_factory() as session:
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="doc-cb-statement-fuzzy-match",
                            attachment_index=0,
                            attachment_name="CAREY01-Statement.pdf",
                            supplier="Connacht Bottlers",
                            document_type="statement",
                            document_date=date(2026, 4, 30),
                            amount=Decimal("1527.48"),
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Connacht Bottlers/statement_fuzzy_match.pdf",
                            needs_review=False,
                            review_reasons=[],
                            source_email_subject="Connacht Bottlers Statement",
                            source_email_sender="Info - Connacht Bottlers <info@connachtbottlers.ie>",
                            extracted_text=CONNACHT_MESSY_STATEMENT_TEXT,
                        ),
                        Transaction(
                            user_id=self.user.id,
                            source_type="bank_statement",
                            source_file="bankstatements/sample.pdf",
                            source_sheet="53747-031",
                            row_number=102,
                            posted_account="93-22-64 - 53747-031",
                            pub="Careys",
                            transaction_date=date(2026, 4, 8),
                            description1="D/D CONNACHT BOTTL",
                            description2="IE26040850610444",
                            debit_amount=Decimal("1037.02"),
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
                    limit=20,
                    annotated_only=False,
                )

            connacht_item = next(item for item in report.transactions if item.row_number == 102)
            self.assertEqual(connacht_item.status, "suggested")
            self.assertEqual(connacht_item.suggested_matches, [])
            self.assertEqual(
                [match.document_type for match in connacht_item.supporting_matches],
                ["statement"],
            )
            self.assertIsNotNone(connacht_item.analysis_note)
            self.assertIn("OCR includes the bank amount 1037.02", connacht_item.analysis_note)
            self.assertIn("structured line recovery is incomplete", connacht_item.analysis_note)
            self.assertEqual(connacht_item.resolution_bucket, "review_supporting_docs")


if __name__ == "__main__":
    unittest.main()
