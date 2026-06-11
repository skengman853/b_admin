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
    from app.models import Document  # noqa: E402
    from app.services.document_ledger import (  # noqa: E402
        LEDGER_ENTRY_CREDIT_NOTE,
        LEDGER_ENTRY_DISCOUNT,
        LEDGER_ENTRY_INVOICE,
        LEDGER_ENTRY_PAYMENT,
        ParsedDocumentLedger,
        ParsedLedgerEntry,
        build_document_ledger,
        build_statement_settlements,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


CONNACHT_SETTLEMENT_TEXT = """JJ Mahon and Sons (Connacht) Ltd
T/A CONNACHT BOTTLERS Grange Carrick-On-Shannon Co. Leitrim,
STATEMENT
CAREYS BAR LTD
CAREYS
38 MARDYKE STREET
ATHLONE
Co. Westmeath N37 AP95
Date:
30/04/2026
Account No.:
CAREY01
14/04/2026
34200
37579
Invoice
863.48
863.48
21/04/2026
34470
37864
Invoice
1,156.72
2,020.20
21/04/2026
34497
EMPTIES 37684
37981
Cr.Note
12.30
2,007.90
21/04/2026
DD-21-04
Receipt
863.48
1,144.42
28/04/2026
DD-28-04
Receipt
1,144.42
0.00
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

BULMERS_STATEMENT_TEXT = """STATEMENT
CAREY'S BAR LTD
Statement Date
30/04/26
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
Item
Amount
876.10
18.00
939.96
1112.45
18.00
851.87
Total Due €
0.00
Payment method: Direct Debit
"""


@unittest.skipIf(_missing_dependencies is not None, f"missing dependency: {_missing_dependencies}")
class DocumentLedgerTest(unittest.TestCase):
    def test_invoice_and_credit_note_documents_normalize_to_common_entries(self) -> None:
        invoice = Document(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            gmail_message_id="invoice-doc",
            attachment_index=0,
            derivation_index=0,
            attachment_name="invoice.pdf",
            supplier="Heineken",
            document_type="invoice",
            document_date=date(2026, 4, 15),
            reference="194159926",
            amount=Decimal("2636.35"),
            vat_amount=Decimal("493.35"),
            local_path="Documents/Heineken/invoice.pdf",
        )
        credit_note = Document(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            gmail_message_id="credit-doc",
            attachment_index=0,
            derivation_index=0,
            attachment_name="credit.pdf",
            supplier="Connacht Bottlers",
            document_type="credit_note",
            document_date=date(2026, 4, 21),
            reference="34497",
            amount=Decimal("12.30"),
            local_path="Documents/Connacht/credit.pdf",
        )

        invoice_ledger = build_document_ledger(invoice)
        credit_ledger = build_document_ledger(credit_note)

        self.assertIsNotNone(invoice_ledger)
        self.assertIsNotNone(credit_ledger)
        assert invoice_ledger is not None
        assert credit_ledger is not None
        self.assertEqual(invoice_ledger.entries[0].entry_kind, LEDGER_ENTRY_INVOICE)
        self.assertEqual(invoice_ledger.entries[0].signed_amount, Decimal("2636.35"))
        self.assertEqual(invoice_ledger.entries[0].vat_amount, Decimal("493.35"))
        self.assertEqual(credit_ledger.entries[0].entry_kind, LEDGER_ENTRY_CREDIT_NOTE)
        self.assertEqual(credit_ledger.entries[0].signed_amount, Decimal("-12.30"))

    def test_connacht_statement_settlements_are_recovered_generically(self) -> None:
        statement = Document(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            gmail_message_id="statement-doc",
            attachment_index=0,
            derivation_index=0,
            attachment_name="CAREY01-Statement.pdf",
            supplier="Connacht Bottlers",
            document_type="statement",
            document_date=date(2026, 4, 30),
            amount=Decimal("0.00"),
            local_path="Documents/Connacht/statement.pdf",
            extracted_text=CONNACHT_SETTLEMENT_TEXT,
        )

        ledger = build_document_ledger(statement)

        self.assertIsNotNone(ledger)
        assert ledger is not None
        self.assertEqual(ledger.statement_kind, "trade_statement")
        self.assertEqual(
            [entry.entry_kind for entry in ledger.entries],
            [
                LEDGER_ENTRY_INVOICE,
                LEDGER_ENTRY_INVOICE,
                LEDGER_ENTRY_CREDIT_NOTE,
                LEDGER_ENTRY_PAYMENT,
                LEDGER_ENTRY_PAYMENT,
            ],
        )

        settlements = build_statement_settlements(ledger)
        self.assertEqual(len(settlements), 2)
        self.assertEqual(settlements[0].payment_entry.reference, "DD-21-04")
        self.assertEqual(
            [entry.reference for entry in settlements[0].component_entries],
            ["34200"],
        )
        self.assertEqual(settlements[1].payment_entry.reference, "DD-28-04")
        self.assertEqual(
            [entry.reference for entry in settlements[1].component_entries],
            ["34470", "34497"],
        )
        self.assertEqual(settlements[1].net_amount, Decimal("1144.42"))

    def _settlement_ledger(self, entries: list[ParsedLedgerEntry]) -> ParsedDocumentLedger:
        return ParsedDocumentLedger(
            document_id=entries[0].document_id,
            supplier="Diageo",
            document_type="statement",
            is_financial=True,
            statement_kind="supplier_statement",
            entries=entries,
        )

    def _ledger_entry(self, *, kind: str, reference: str, event_date: date, amount: str) -> ParsedLedgerEntry:
        value = Decimal(amount)
        signed = -abs(value) if kind in {LEDGER_ENTRY_CREDIT_NOTE, LEDGER_ENTRY_DISCOUNT} else value
        return ParsedLedgerEntry(
            document_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            document_type="statement",
            supplier="Diageo",
            entry_kind=kind,
            event_date=event_date,
            reference=reference,
            amount=value,
            signed_amount=signed,
        )

    def test_settlement_nets_prompt_payment_discount_against_invoice(self) -> None:
        # invoice 4034.90 with a 2.5% settlement discount of 100.87: the bank
        # debit is 3934.03, which only reconciles when the discount row joins
        # the settlement group.
        ledger = self._settlement_ledger(
            [
                self._ledger_entry(kind=LEDGER_ENTRY_INVOICE, reference="9263290802", event_date=date(2026, 3, 5), amount="4034.90"),
                self._ledger_entry(kind=LEDGER_ENTRY_DISCOUNT, reference="SETT-DISC", event_date=date(2026, 3, 5), amount="100.87"),
                self._ledger_entry(kind=LEDGER_ENTRY_PAYMENT, reference="2503704272", event_date=date(2026, 3, 10), amount="3934.03"),
            ]
        )

        settlements = build_statement_settlements(ledger)

        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0].payment_entry.reference, "2503704272")
        self.assertEqual(
            {entry.reference for entry in settlements[0].component_entries},
            {"9263290802", "SETT-DISC"},
        )
        self.assertEqual(settlements[0].net_amount, Decimal("3934.03"))

    def test_settlement_subset_match_tolerates_one_cent(self) -> None:
        ledger = self._settlement_ledger(
            [
                self._ledger_entry(kind=LEDGER_ENTRY_INVOICE, reference="INV-1", event_date=date(2026, 3, 5), amount="100.01"),
                self._ledger_entry(kind=LEDGER_ENTRY_PAYMENT, reference="PAY-1", event_date=date(2026, 3, 10), amount="100.00"),
            ]
        )

        settlements = build_statement_settlements(ledger)

        self.assertEqual(len(settlements), 1)
        self.assertEqual(
            [entry.reference for entry in settlements[0].component_entries],
            ["INV-1"],
        )

    def test_statement_of_account_settlement_is_recovered_generically(self) -> None:
        statement = Document(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            gmail_message_id="heineken-statement-doc",
            attachment_index=0,
            derivation_index=0,
            attachment_name="heineken_statement.pdf",
            supplier="Heineken",
            document_type="statement",
            document_date=date(2026, 4, 2),
            amount=Decimal("0.00"),
            local_path="Documents/Heineken/statement.pdf",
            extracted_text=HEINEKEN_STATEMENT_TEXT,
        )

        ledger = build_document_ledger(statement)

        self.assertIsNotNone(ledger)
        assert ledger is not None
        settlements = build_statement_settlements(ledger)
        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0].payment_entry.reference, "2000025959")
        self.assertEqual(
            [entry.reference for entry in settlements[0].component_entries],
            ["194101304", "194101305", "194101306"],
        )
        self.assertEqual(settlements[0].net_amount, Decimal("3816.62"))

    def test_columnar_statement_of_account_lines_become_invoice_entries(self) -> None:
        statement = Document(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            gmail_message_id="bulmers-statement-doc",
            attachment_index=0,
            derivation_index=0,
            attachment_name="bulmers_statement.pdf",
            supplier="Bulmers",
            document_type="statement",
            document_date=date(2026, 4, 30),
            amount=Decimal("0.00"),
            local_path="Documents/Bulmers/statement.pdf",
            extracted_text=BULMERS_STATEMENT_TEXT,
        )

        ledger = build_document_ledger(statement)

        self.assertIsNotNone(ledger)
        assert ledger is not None
        self.assertEqual(
            [(entry.reference, entry.event_date.isoformat(), str(entry.amount)) for entry in ledger.entries[:6]],
            [
                ("4100706", "2026-03-25", "876.10"),
                ("4112987", "2026-03-31", "18.00"),
                ("4120677", "2026-04-02", "939.96"),
                ("4150604", "2026-04-15", "1112.45"),
                ("4150707", "2026-04-15", "18.00"),
                ("4188699", "2026-04-30", "851.87"),
            ],
        )
        self.assertTrue(
            all(entry.entry_kind == LEDGER_ENTRY_INVOICE for entry in ledger.entries[:6])
        )

    def test_ai_statement_short_codes_become_invoice_and_payment_entries(self) -> None:
        statement = Document(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            gmail_message_id="bulmers-statement-ai-doc",
            attachment_index=0,
            derivation_index=0,
            attachment_name="bulmers_statement_ai.pdf",
            supplier="Bulmers",
            document_type="statement",
            document_date=date(2026, 4, 30),
            amount=Decimal("0.00"),
            local_path="Documents/Bulmers/statement_ai.pdf",
            extracted_text="weak ocr text",
            ai_extraction_payload={
                "statement_kind": "supplier_statement",
                "is_financial": True,
                "entries": [
                    {
                        "event_date": "2026-03-25",
                        "reference": "4100706",
                        "transaction_type": "INV",
                        "due_date": "2026-04-01",
                        "amount": "876.10",
                        "raw_text": "25/03/26 INV 4100706 876.10",
                    },
                    {
                        "event_date": "2026-04-01",
                        "reference": "DD-01-04",
                        "transaction_type": "PMT",
                        "due_date": "2026-04-01",
                        "amount": "-876.10",
                        "raw_text": "01/04/26 PMT DD-01-04 876.10",
                    },
                ],
            },
        )

        ledger = build_document_ledger(statement)

        self.assertIsNotNone(ledger)
        assert ledger is not None
        self.assertEqual(
            [(entry.entry_kind, entry.reference, str(entry.amount)) for entry in ledger.entries],
            [
                (LEDGER_ENTRY_INVOICE, "4100706", "876.10"),
                (LEDGER_ENTRY_PAYMENT, "DD-01-04", "876.10"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
