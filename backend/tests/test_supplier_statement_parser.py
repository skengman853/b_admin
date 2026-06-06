from __future__ import annotations

import sys
import types
import unittest
import uuid
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
    from app.models import Document  # noqa: E402
    from app.services.supplier_statement_parser import parse_supplier_statement  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


DIAGEO_STATEMENT_TEXT = """STATEMENT
Page No.
Date
Currency

1
of
30.04.2026
EUR

1

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
WESTMEATH

Diageo Ireland
Credit Management Team
St. James's Gate
Dublin 8

Doc
Date

Billing
Doc

VAT Reg No: IE9I45806S

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

D110852766

09.04.2026
07.04.2026
17.04.2026
15.04.2026
23.04.2026
21.04.2026
30.04.2026
28.04.2026

D110852769
D110855861
D110859131

Total Due
0.00

Total Sett Disc
275.17-
"""

DIAGEO_SUB_ACCOUNT_TEXT = """SUB ACCOUNT STATEMENT

Diageo Ireland
Customer Contact Centre
St James's Gate
Dublin 8

Document Date
02.04.2026
01.03.2026 - 31.03.2026

Invoice Address
314773
CAREY'S BAR LIMITED
T/A CAREY'S BAR
38 MARDYKE STREET
ATHLONE N37 AP95
WESTMEATH

Details
Accumulated discounts
Commercial Discounts
Settlement Discount

Opening Balance
0.00
-5,011.03

Net monthly transactions
-453.34

Closing Balance EUR

-5,464.37
"""

DIAGEO_KEG_FLOW_TEXT = """Monthly Keg Flow Position
Page No. 1 of 1
Date
02.04.2026

Account Number
314773

Statement Address

CAREY'S BAR LIMITED
T/A CAREY'S BAR
38 MARDYKE STREET
ATHLONE N37 AP95

This is not a financial Document
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

HEINEKEN_STATEMENT_TEXT = """STATEMENT OF ACCOUNT

Maye Carey
For attention of: Accounts Payable
Careys Pub
Careys Bar Limited
38 Mardyke Street
Athlone
Co Westmeath
N37 AP95

Date: 02.04.2026
Customer Account No: 2016632103
Dear Sir/Madam,
Please find below your account statement with all items between 01.03.2026 To 31.03.2026:
Reference
Number

Document
Number

Document
Type

Document
Date

Due
Date

Original
Amount

Residual
B/F

Adjusted
Amount

Balance

Document Currency - EUR
Opening Balance as on 01.03.2026

0.00

1800043903

0194101304 Invoice

04.03.2026

04.03.2026

3,719.56

0.00

-3,719.56

0.00

1800043907

0194101305 Invoice

04.03.2026

04.03.2026

37.33

0.00

-37.33

0.00

1800043911

0194101306 Invoice

04.03.2026

04.03.2026

59.73

0.00

-59.73

0.00

2000025959

Payment

06.03.2026

06.03.2026

-3,816.62

0.00

3,816.62

0.00

Closing Balance as on 31.03.2026

0.00

Settlement Discount of EUR 3,914.99 is available for payment.
"""

BULMERS_STATEMENT_TEXT = """Customer Statement,1001,,,,31/12/16,113480.60

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
Branch
No
Item
Amount
876.10
18.00
939.96
1112.45
18.00
851.87
Overdue €
Amount
Paid
Net Amount
-876.10
-18.00
-939.96
-1112.45
-18.00
0.00
0.00
0.00
0.00
0.00
0.00
851.87
Total Due €
0.00
Payment method: Direct Debit
"""


if _missing_dependencies:
    class SupplierStatementParserTests(unittest.TestCase):
        @unittest.skip(f"supplier statement parser tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class SupplierStatementParserTests(unittest.TestCase):
        def _build_document(self, attachment_name: str, extracted_text: str) -> Document:
            return Document(
                id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                gmail_message_id=f"message-{attachment_name}",
                attachment_index=0,
                attachment_name=attachment_name,
                supplier="Diageo",
                document_type="statement",
                extraction_status="extracted",
                local_path=f"Documents/Diageo/{attachment_name}",
                extracted_text=extracted_text,
            )

        def test_parses_diageo_month_end_statement_lines(self) -> None:
            parsed = parse_supplier_statement(
                self._build_document("diageo_statement.pdf", DIAGEO_STATEMENT_TEXT)
            )

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "supplier_statement")
            self.assertTrue(parsed.is_financial)
            self.assertEqual(parsed.account_number, "314773")
            self.assertEqual(str(parsed.total_due), "0.00")
            self.assertEqual(str(parsed.settlement_discount_total), "-275.17")
            self.assertEqual(parsed.invoice_references[0], "9263312263")
            self.assertEqual(parsed.payment_references[0], "2503715694")
            self.assertEqual(len(parsed.entries), 8)
            self.assertEqual(parsed.entries[0].transaction_type, "INVOIC")
            self.assertEqual(parsed.entries[1].transaction_type, "PAYMNT")

        def test_prefers_ai_extracted_statement_payload_when_present(self) -> None:
            document = self._build_document("diageo_statement_ai.pdf", "weak ocr text")
            document.ai_extraction_payload = {
                "statement_kind": None,
                "is_financial": True,
                "account_number": "314773",
                "account_name": "Careys Bar Limited",
                "period_start": "2026-04-01",
                "period_end": "2026-04-30",
                "total_due": "0.00",
                "settlement_discount_total": "-275.17",
                "note": "Recovered rows from AI extraction.",
                "entries": [
                    {
                        "event_date": "2026-04-02",
                        "reference": "9263312263",
                        "transaction_type": "INVOIC",
                        "due_date": "2026-04-09",
                        "amount": "3945.57",
                        "raw_text": "02.04.2026 9263312263 INVOIC 09.04.2026 3945.57",
                    },
                    {
                        "event_date": "2026-04-07",
                        "reference": "2503715694",
                        "transaction_type": "PAYMNT",
                        "due_date": "2026-04-07",
                        "amount": "-3945.57",
                        "raw_text": "07.04.2026 2503715694 PAYMNT 07.04.2026 3945.57",
                    },
                ],
            }

            parsed = parse_supplier_statement(document)

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "supplier_statement")
            self.assertEqual(parsed.account_number, "314773")
            self.assertEqual(parsed.invoice_references, ["9263312263"])
            self.assertEqual(parsed.payment_references, ["2503715694"])
            self.assertEqual(len(parsed.entries), 2)
            self.assertEqual(parsed.entries[0].transaction_type, "Invoice")
            self.assertEqual(parsed.entries[1].transaction_type, "Payment")
            self.assertEqual(str(parsed.entries[1].amount), "3945.57")
            self.assertIn("Structured AI extraction was used", parsed.note or "")

        def test_parses_diageo_sub_account_statement(self) -> None:
            parsed = parse_supplier_statement(
                self._build_document("diageo_sub_statement.pdf", DIAGEO_SUB_ACCOUNT_TEXT)
            )

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "sub_account_statement")
            self.assertTrue(parsed.is_financial)
            self.assertEqual(parsed.account_number, "314773")
            self.assertEqual(parsed.period_start.isoformat(), "2026-03-01")
            self.assertEqual(parsed.period_end.isoformat(), "2026-03-31")
            self.assertEqual(str(parsed.closing_balance), "-5464.37")

        def test_marks_keg_flow_as_non_financial(self) -> None:
            parsed = parse_supplier_statement(
                self._build_document("diageo_keg_flow.pdf", DIAGEO_KEG_FLOW_TEXT)
            )

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "keg_flow_statement")
            self.assertFalse(parsed.is_financial)
            self.assertEqual(parsed.account_number, "314773")
            self.assertIn("should not be treated as a financial settlement", parsed.note)

        def test_parses_connacht_trade_statement_entries(self) -> None:
            document = self._build_document("connacht_statement.pdf", CONNACHT_STATEMENT_TEXT)
            document.supplier = "Connacht Bottlers"
            parsed = parse_supplier_statement(document)

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "trade_statement")
            self.assertTrue(parsed.is_financial)
            self.assertEqual(parsed.account_number, "CAREY01")
            self.assertEqual(parsed.account_name, "CAREYS BAR LTD, CAREYS, 38 MARYDYKE STREET")
            self.assertEqual(parsed.invoice_references[:2], ["34508", "34769"])
            self.assertEqual(parsed.payment_references[:1], ["DD-29-04"])
            self.assertEqual(
                [
                    (entry.transaction_type, entry.reference, str(entry.amount))
                    for entry in parsed.entries
                ],
                [
                    ("Invoice", "34508", "740.98"),
                    ("Invoice", "34769", "786.50"),
                    ("Receipt", "DD-29-04", "786.50"),
                ],
            )

        def test_parses_connacht_trade_statement_via_alias_family(self) -> None:
            document = self._build_document("connacht_statement_alias.pdf", CONNACHT_STATEMENT_TEXT)
            document.supplier = "JJ Mahon and Sons"
            parsed = parse_supplier_statement(document)

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "trade_statement")
            self.assertEqual(parsed.account_number, "CAREY01")

        def test_parses_statement_of_account_entries(self) -> None:
            document = self._build_document("heineken_statement.pdf", HEINEKEN_STATEMENT_TEXT)
            document.supplier = "Heineken"
            parsed = parse_supplier_statement(document)

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "supplier_statement")
            self.assertTrue(parsed.is_financial)
            self.assertEqual(parsed.account_number, "2016632103")
            self.assertEqual(parsed.period_start.isoformat(), "2026-03-01")
            self.assertEqual(parsed.period_end.isoformat(), "2026-03-31")
            self.assertEqual(str(parsed.total_due), "0.00")
            self.assertEqual(str(parsed.closing_balance), "0.00")
            self.assertEqual(str(parsed.settlement_discount_total), "3914.99")
            self.assertEqual(
                [(entry.transaction_type, entry.reference, str(entry.amount)) for entry in parsed.entries],
                [
                    ("Invoice", "194101304", "3719.56"),
                    ("Invoice", "194101305", "37.33"),
                    ("Invoice", "194101306", "59.73"),
                    ("Payment", "2000025959", "3816.62"),
                ],
            )

        def test_parses_statement_of_account_without_supplier_name(self) -> None:
            document = self._build_document("statement_of_account.pdf", HEINEKEN_STATEMENT_TEXT)
            document.supplier = None
            parsed = parse_supplier_statement(document)

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "supplier_statement")
            self.assertEqual(parsed.account_number, "2016632103")

        def test_parses_columnar_statement_of_account_entries(self) -> None:
            document = self._build_document("bulmers_statement.pdf", BULMERS_STATEMENT_TEXT)
            document.supplier = "Bulmers"
            parsed = parse_supplier_statement(document)

            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.statement_kind, "supplier_statement")
            self.assertTrue(parsed.is_financial)
            self.assertEqual(parsed.period_end.isoformat(), "2026-04-30")
            self.assertEqual(
                [(entry.transaction_type, entry.reference, entry.event_date.isoformat(), entry.due_date.isoformat(), str(entry.amount)) for entry in parsed.entries[:6]],
                [
                    ("Invoice", "4100706", "2026-03-25", "2026-04-01", "876.10"),
                    ("Invoice", "4112987", "2026-03-31", "2026-04-07", "18.00"),
                    ("Invoice", "4120677", "2026-04-02", "2026-04-09", "939.96"),
                    ("Invoice", "4150604", "2026-04-15", "2026-04-22", "1112.45"),
                    ("Invoice", "4150707", "2026-04-15", "2026-04-22", "18.00"),
                    ("Invoice", "4188699", "2026-04-30", "2026-05-07", "851.87"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
