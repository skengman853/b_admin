from __future__ import annotations

import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_candidates import extract_multi_invoice_candidates  # noqa: E402
from app.services.document_extraction_rules import build_extraction_fields, extract_currency, extract_vat_amount  # noqa: E402

_ai_import_error: str | None = None
try:  # pragma: no cover - host Python may not have full app deps
    from app.services.ai_document_extraction import (  # noqa: E402
        AIDocumentExtractionResult,
        _build_ai_extraction_messages,
        merge_ai_extraction,
    )
except ModuleNotFoundError as exc:  # pragma: no cover
    _ai_import_error = str(exc)


CHRIS_LYNCH_SHORT_INVOICE_TEXT = """Invoice
Invoice No.: OUT-75972
Invoice Date: 30-03-26

Tax
13.50%

Order Total
€431.72

Net Total
€431.72

VAT
€58.28

Grand Total

€490.00
"""


DAVID_CAMPBELL_INVOICE_TEXT = """David Campbell t/a little luxuries

Invoice

Invoice No:
262

Date:
04/23/2026

Subtotal
€350.00

VAT 13.5% (€350.00)
€47.25

Total
€397.25
"""


DAVID_CAMPBELL_SECOND_INVOICE_TEXT = """David Campbell t/a little luxuries

Invoice

Invoice No:
255

Date:
03/12/2026

Description
canal turn

Quantity

Rate

VAT

Amount

3.5

€350.00

13.5%

€1,225.00

Subtotal

€1,225.00

VAT 13.5% (€1,225.00)

€165.38

Total

€1,390.38
"""


DAVID_CAMPBELL_THIRD_INVOICE_TEXT = """David Campbell t/a little luxuries

Invoice

Invoice No:
258

Date:
04/02/2026

Description
works at canal turn and careys bar

Quantity

Rate

VAT

Amount

4.75

€350.00

13.5%

€1,662.50

Subtotal

€1,662.50

VAT 13.5% (€1,662.50)

€224.44

Total

€1,886.94
"""


RAILWAY_RECEIPT_TEXT = """Receipt
Invoice number UIMSS74R-0003
Receipt number 2277-2700
Date paid
April 25, 2026

Amount paid
$5.00 USD
"""


LOVELL_MULTI_INVOICE_TEXT = """Lovell Bros. Ltd.

INVOICE 881489

Qty
Price
Discount
Total

1
8.09
0.00
8.09

VAT Summary
VAT %

23.00

Nett Total
298.58

VAT Total
68.66

Total Nett
298.58
VAT
68.66

TOTAL
367.24

INVOICE 881548

VAT Total
17.84

TOTAL
95.40
"""


SPARSE_PROMO_STATEMENT_TEXT = """May Promotional Activity 2026 Connacht Bottlers

Promo Support
€47.50
"""

BULMERS_ARCHIVE_INVOICE_TEXT = """INVOICE,9890200,9890201,1466,60008348,12/12/16,2205.36,273263,15/12/16,60009694,,,00060~CCCI_2016347_225404.TXT

Issued by
Bulmers Ireland

INVOICE
Invoiced To

CAREY'S BAR LTD
T/A CAREY'S

Invoice Number

4150707

Delivery Date

15/04/26

Order Date

14/04/26

VAT

Invoice Date: 15/04/26

Goods Value

VAT Value

0.00
18.00

0.00
0.00

18.00

0.00

Total €

18.00

Payment Method:

Direct Debit
"""

CONNACHT_ARCHIVE_INVOICE_TEXT = """JJ Mahon and Sons (Connacht) Ltd
T/A CONNACHT BOTTLERS Grange Carrick-On-Shannon Co. Leitrim,
Phone (071) 967 1793 email info@connachtbottlers.ie
Vat Reg IE4110224AH
INVOICE
Billing address: Delivery address: 11
CAREYS BAR LTD CAREYS
T/A CAREYS 38 MARYDYKE STREET
38 MARYDYKE STREET
ATHLONE ATHLONE
Co. Westmeath Co. Westmeath N37 AP95
INVOICE NO. INVOICE DATE A/C NO. YOUR REF ORDER NO. OPERATOR
34036 09/04/2026 CAREY01 DEL BY REP 37374 AIDAN
Code Case Single Description Pack Price VAT Value
10518 3 LA SUBIDA SAUV BLANC 187.5ML 1/4 BT 24 46.00 23.00% 138.00
Vat Breakdown Total Goods: 138.00 €
Rate Goods Vat
Total VAT: 31.74 €
23.00% 138.00 31.74
0.00% 0.00 0.00 Deposit Fee: 0.00 €
0.00% 0.00 0.00
Invoice Total 169.74 €
0.00% 0.00 0.00
(#) Denotes Deposit Re-Turn Item
"""


LOVELL_MIXED_RATES_TEXT = """Lovell Bros. Ltd.

INVOICE 883058

13/04/2026

VAT Total
13.50
31.80
4.29
23.00
523.51
120.40

Total Nett
555.31
VAT
124.69
TOTAL
680.00

INVOICE 883145

14/04/2026

VAT Total
74.71
TOTAL
399.58
"""


LOVELL_LIVE_SUMMARY_BLOCK_TEXT = """Lovell Bros. Ltd.

INVOICE 883148

13/04/2026

Delivery for Load No. 4015 - Account Sale:
Code
Description
4SPL
4BSP4
490SRB1S
4ST3S
41HBT
41QBT
1HWP4
1QWP4

Total
139.02
95.12
14.40
18.57
24.06
27.45
24.16
21.96

VAT Summary
VAT %
23.00

Nett Total
364.74

VAT Total
83.88

Total Nett
VAT

TOTAL

364.74
83.88

448.62

170.99
117.00
17.71
22.84
29.59
33.76
29.72
27.01

INVOICE 884291

22/04/2026

Code
Description
TAKT001
BSPWA55
R44BM1
LT88
4ST3S
2WP4
1H1QWR
245WB
1HWC
TSL11090R

Total
62.16
9.88
5.82
9.48
19.67
11.16
0.63
4.40
1.10
171.95

VAT Summary
VAT %
23.00

Nett Total
296.25

VAT Total
68.13

Total Nett
VAT

TOTAL

296.25
68.13

364.38

76.46
12.15
7.16
11.66
24.19
13.73
0.77
5.41
1.35
211.50
"""


class DocumentExtractionTests(unittest.TestCase):
    def test_extracts_vat_amount_from_invoice(self) -> None:
        self.assertEqual(str(extract_vat_amount(CHRIS_LYNCH_SHORT_INVOICE_TEXT, "invoice")), "58.28")
        self.assertEqual(str(extract_vat_amount(DAVID_CAMPBELL_INVOICE_TEXT, "invoice")), "47.25")
        self.assertEqual(str(extract_vat_amount(DAVID_CAMPBELL_SECOND_INVOICE_TEXT, "invoice")), "165.38")
        self.assertEqual(str(extract_vat_amount(DAVID_CAMPBELL_THIRD_INVOICE_TEXT, "invoice")), "224.44")

    def test_detects_currency(self) -> None:
        self.assertEqual(extract_currency(DAVID_CAMPBELL_INVOICE_TEXT), "EUR")
        self.assertEqual(extract_currency(RAILWAY_RECEIPT_TEXT), "USD")

    def test_builds_extraction_fields_with_confidence(self) -> None:
        payload = build_extraction_fields(
            extracted_text=DAVID_CAMPBELL_INVOICE_TEXT,
            supplier="Little Luxuries",
            document_type="invoice",
            subject="PAID: Invoice 262",
            attachment_name="invoice_262.pdf",
            needs_review=False,
        )

        self.assertEqual(str(payload["document_date"]), "2026-04-23")
        self.assertEqual(payload["reference"], "262")
        self.assertEqual(str(payload["amount"]), "397.25")
        self.assertEqual(str(payload["vat_amount"]), "47.25")
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(payload["extraction_status"], "extracted")
        self.assertFalse(payload["needs_review"])
        self.assertEqual(payload["review_reasons"], [])
        self.assertGreater(payload["confidence_score"], 0.7)

    def test_marks_multi_invoice_documents_for_review(self) -> None:
        payload = build_extraction_fields(
            extracted_text=LOVELL_MULTI_INVOICE_TEXT,
            supplier="Lovell Bros. Ltd.",
            document_type="invoice",
            subject="Statement Attached",
            attachment_name="INS1.PDF",
            needs_review=False,
        )

        self.assertIsNone(payload["reference"])
        self.assertIsNone(payload["amount"])
        self.assertIsNone(payload["vat_amount"])
        self.assertEqual(payload["extraction_status"], "review")
        self.assertTrue(payload["needs_review"])
        self.assertEqual(payload["review_reasons"], [
            "multiple_invoice_records",
            "missing_document_date",
            "missing_amount",
            "low_confidence_extraction",
        ])
        self.assertLess(payload["confidence_score"], 0.7)

    def test_marks_sparse_statement_with_missing_date_and_low_confidence(self) -> None:
        payload = build_extraction_fields(
            extracted_text=SPARSE_PROMO_STATEMENT_TEXT,
            supplier="Connacht Bottlers",
            document_type="statement",
            subject="Connacht Bottlers Statement",
            attachment_name="May Promotional Activity 2026 Connacht Bottlers.pdf",
            needs_review=False,
        )

        self.assertIsNone(payload["document_date"])
        self.assertEqual(str(payload["amount"]), "47.50")
        self.assertEqual(payload["extraction_status"], "extracted")
        self.assertTrue(payload["needs_review"])
        self.assertEqual(payload["review_reasons"], [
            "missing_document_date",
            "low_confidence_extraction",
        ])

    @unittest.skipIf(_ai_import_error is not None, f"AI extraction helper unavailable: {_ai_import_error}")
    def test_ai_statement_prompt_includes_row_contract_and_family_hint(self) -> None:
        document = types.SimpleNamespace(
            document_type="statement",
            supplier="Diageo",
            attachment_name="diageo_statement.pdf",
            source_email_subject="Diageo month end statement",
        )

        messages = _build_ai_extraction_messages(
            document=document,
            extracted_text="STATEMENT\nTotal Sett Disc\n9263312263\nINVOIC\n",
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("prioritize row-level recovery", messages[0]["content"])
        self.assertIn("Statement parser family hint: diageo_erp_statement", messages[1]["content"])
        self.assertIn("keep one JSON entry per financial row", messages[1]["content"])
        self.assertIn("Use `clearing_reference` only for a second linked document number", messages[1]["content"])
        self.assertIn("Flattened OCR may list columns in separate blocks", messages[1]["content"])

    @unittest.skipIf(_ai_import_error is not None, f"AI extraction helper unavailable: {_ai_import_error}")
    def test_ai_merge_can_promote_sparse_statement_into_structured_extraction(self) -> None:
        payload = build_extraction_fields(
            extracted_text=SPARSE_PROMO_STATEMENT_TEXT,
            supplier="Connacht Bottlers",
            document_type="statement",
            subject="Connacht Bottlers Statement",
            attachment_name="May Promotional Activity 2026 Connacht Bottlers.pdf",
            needs_review=False,
        )
        document = types.SimpleNamespace(
            document_type="statement",
            supplier="Connacht Bottlers",
            attachment_name="statement.pdf",
            source_email_subject="Connacht statement",
            ai_extraction_status=None,
            ai_extraction_provider=None,
            ai_extraction_model=None,
            ai_extraction_payload=None,
            ai_extracted_at=None,
        )
        ai_result = AIDocumentExtractionResult(
            document_date="2026-05-31",
            statement_kind="trade_statement",
            is_financial=True,
            account_number="CAREY01",
            closing_balance="47.50",
            confidence_score=0.88,
            note="Recovered statement metadata from weak OCR text.",
            entries=[
                {
                    "event_date": "2026-05-31",
                    "reference": "DD-31-05",
                    "transaction_type": "Receipt",
                    "amount": "47.50",
                    "raw_text": "31/05/2026 DD-31-05 Receipt 47.50",
                }
            ],
        )

        merged = merge_ai_extraction(
            document=document,
            extraction_fields=payload,
            ai_result=ai_result,
        )

        self.assertEqual(str(merged["document_date"]), "2026-05-31")
        self.assertEqual(merged["extraction_status"], "extracted")
        self.assertFalse(merged["needs_review"])
        self.assertEqual(merged["review_reasons"], [])
        self.assertEqual(document.ai_extraction_status, "completed")
        self.assertIsNotNone(document.ai_extraction_payload)
        self.assertEqual(document.ai_extraction_payload["statement_kind"], "trade_statement")

    @unittest.skipIf(_ai_import_error is not None, f"AI extraction helper unavailable: {_ai_import_error}")
    def test_ai_merge_keeps_incomplete_statement_rows_in_review(self) -> None:
        payload = build_extraction_fields(
            extracted_text=SPARSE_PROMO_STATEMENT_TEXT,
            supplier="Diageo",
            document_type="statement",
            subject="Diageo month end statement",
            attachment_name="diageo_statement.pdf",
            needs_review=False,
        )
        document = types.SimpleNamespace(
            document_type="statement",
            supplier="Diageo",
            attachment_name="diageo_statement.pdf",
            source_email_subject="Diageo month end statement",
            ai_extraction_status=None,
            ai_extraction_provider=None,
            ai_extraction_model=None,
            ai_extraction_payload=None,
            ai_extracted_at=None,
        )
        ai_result = AIDocumentExtractionResult(
            document_date="2026-03-31",
            statement_kind="diageo_erp_statement",
            is_financial=True,
            account_number="CAREY01",
            period_start="2026-03-01",
            period_end="2026-03-31",
            confidence_score=0.82,
            entries=[
                {
                    "event_date": "2026-03-05",
                    "reference": "9263290802",
                    "transaction_type": "INVOIC",
                    "due_date": "2026-03-12",
                    "amount": None,
                    "raw_text": "9263290802 INVOIC 05.03.2026 12.03.2026",
                },
                {
                    "event_date": "2026-03-11",
                    "reference": "2503701436",
                    "transaction_type": "PAYMNT",
                    "amount": None,
                    "raw_text": "2503701436 PAYMNT 11.03.2026",
                },
            ],
        )

        merged = merge_ai_extraction(
            document=document,
            extraction_fields=payload,
            ai_result=ai_result,
        )

        self.assertEqual(merged["extraction_status"], "review")
        self.assertTrue(merged["needs_review"])
        self.assertIn("statement_rows_missing_amounts", merged["review_reasons"])
        self.assertIn("low_confidence_extraction", merged["review_reasons"])
        self.assertLess(merged["confidence_score"], 0.7)

    @unittest.skipIf(_ai_import_error is not None, f"AI extraction helper unavailable: {_ai_import_error}")
    def test_ai_merge_replaces_pub_supplier_with_extracted_supplier(self) -> None:
        payload = build_extraction_fields(
            extracted_text=SPARSE_PROMO_STATEMENT_TEXT,
            supplier="Canal Turn",
            document_type="statement",
            subject="Canal Turn/Sub Account Statements/file.pdf",
            attachment_name="Canal Turn - Sub Account Statements TCT003.pdf",
            needs_review=False,
        )
        document = types.SimpleNamespace(
            document_type="statement",
            supplier="Canal Turn",
            attachment_name="Canal Turn - Sub Account Statements TCT003.pdf",
            source_email_subject="Canal Turn/Sub Account Statements/file.pdf",
            ai_extraction_status=None,
            ai_extraction_provider=None,
            ai_extraction_model=None,
            ai_extraction_payload=None,
            ai_extracted_at=None,
        )
        ai_result = AIDocumentExtractionResult(
            supplier="Diageo Ireland",
            document_date="2026-03-31",
            statement_kind="sub_account_statement",
            is_financial=True,
        )

        merge_ai_extraction(
            document=document,
            extraction_fields=payload,
            ai_result=ai_result,
        )

        self.assertEqual(document.supplier, "Diageo")

    @unittest.skipIf(_ai_import_error is not None, f"AI extraction helper unavailable: {_ai_import_error}")
    def test_ai_merge_never_assigns_pub_name_as_supplier(self) -> None:
        payload = build_extraction_fields(
            extracted_text=SPARSE_PROMO_STATEMENT_TEXT,
            supplier="Other",
            document_type="statement",
            subject="statement.pdf",
            attachment_name="statement.pdf",
            needs_review=True,
        )
        document = types.SimpleNamespace(
            document_type="statement",
            supplier="Other",
            attachment_name="statement.pdf",
            source_email_subject="statement.pdf",
            ai_extraction_status=None,
            ai_extraction_provider=None,
            ai_extraction_model=None,
            ai_extraction_payload=None,
            ai_extracted_at=None,
        )
        ai_result = AIDocumentExtractionResult(
            supplier="Careys Bar",
            document_date="2026-03-31",
            statement_kind="generic_statement",
            is_financial=True,
        )

        merge_ai_extraction(
            document=document,
            extraction_fields=payload,
            ai_result=ai_result,
        )

        self.assertEqual(document.supplier, "Other")

    def test_extracts_multi_invoice_candidates(self) -> None:
        candidates = extract_multi_invoice_candidates(
            text=LOVELL_MULTI_INVOICE_TEXT,
            document_type="invoice",
            subject="Statement Attached",
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["reference"], "881489")
        self.assertIsNone(candidates[0]["document_date"])
        self.assertEqual(str(candidates[0]["amount"]), "367.24")
        self.assertEqual(str(candidates[0]["vat_amount"]), "68.66")
        self.assertEqual(candidates[0]["currency"], None)

        self.assertEqual(candidates[1]["reference"], "881548")
        self.assertIsNone(candidates[1]["document_date"])
        self.assertEqual(str(candidates[1]["amount"]), "95.40")
        self.assertEqual(str(candidates[1]["vat_amount"]), "17.84")

    def test_extracts_multi_invoice_candidates_from_summary_totals(self) -> None:
        candidates = extract_multi_invoice_candidates(
            text=LOVELL_MIXED_RATES_TEXT,
            document_type="invoice",
            subject="Statement Attached",
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["reference"], "883058")
        self.assertEqual(str(candidates[0]["document_date"]), "2026-04-13")
        self.assertEqual(str(candidates[0]["amount"]), "680.00")
        self.assertEqual(str(candidates[0]["vat_amount"]), "124.69")

        self.assertEqual(candidates[1]["reference"], "883145")
        self.assertEqual(str(candidates[1]["document_date"]), "2026-04-14")
        self.assertEqual(str(candidates[1]["amount"]), "399.58")
        self.assertEqual(str(candidates[1]["vat_amount"]), "74.71")

    def test_extracts_multi_invoice_candidates_from_live_summary_blocks(self) -> None:
        candidates = extract_multi_invoice_candidates(
            text=LOVELL_LIVE_SUMMARY_BLOCK_TEXT,
            document_type="invoice",
            subject="Statement Attached",
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["reference"], "883148")
        self.assertEqual(str(candidates[0]["document_date"]), "2026-04-13")
        self.assertEqual(str(candidates[0]["amount"]), "448.62")
        self.assertEqual(str(candidates[0]["vat_amount"]), "83.88")

        self.assertEqual(candidates[1]["reference"], "884291")
        self.assertEqual(str(candidates[1]["document_date"]), "2026-04-22")
        self.assertEqual(str(candidates[1]["amount"]), "364.38")
        self.assertEqual(str(candidates[1]["vat_amount"]), "68.13")

    def test_marks_suspicious_amounts_for_review(self) -> None:
        payload = build_extraction_fields(
            extracted_text="INVOICE 884291",
            supplier="Lovell Bros. Ltd.",
            document_type="invoice",
            subject="Statement Attached",
            attachment_name="INS1.PDF",
            existing_document_date=None,
            existing_reference="884291",
            existing_amount=Decimal("171.95"),
            existing_vat_amount=Decimal("364.38"),
            existing_currency=None,
            existing_review_reasons=[],
            needs_review=False,
            prefer_existing_values=True,
        )

        self.assertEqual(payload["extraction_status"], "review")
        self.assertTrue(payload["needs_review"])
        self.assertIn("suspicious_amounts", payload["review_reasons"])

    def test_builds_archive_invoice_fields_from_filename_and_total(self) -> None:
        payload = build_extraction_fields(
            extracted_text=BULMERS_ARCHIVE_INVOICE_TEXT,
            supplier="Bulmers",
            document_type="invoice",
            subject="Bulmers Ireland/Invoices/Careys Bar/Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026 - Linked.pdf",
            attachment_name="Careys Bar - Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026.pdf",
            needs_review=False,
        )

        self.assertEqual(str(payload["document_date"]), "2026-04-15")
        self.assertEqual(payload["reference"], "4150707")
        self.assertEqual(str(payload["amount"]), "18.00")
        self.assertIsNone(payload["vat_amount"])

    def test_builds_connacht_archive_invoice_fields_from_filename_and_total(self) -> None:
        payload = build_extraction_fields(
            extracted_text=CONNACHT_ARCHIVE_INVOICE_TEXT,
            supplier="Connacht Bottlers",
            document_type="invoice",
            subject="JJ Mahon and Sons/Invoices/Careys Bar/JJ Mahon - INV-227 - No 34036 - Date - 09-04-2026.pdf",
            attachment_name="JJ Mahon - INV-227 - No 34036 - Date - 09-04-2026.pdf",
            needs_review=False,
        )

        self.assertEqual(str(payload["document_date"]), "2026-04-09")
        self.assertEqual(payload["reference"], "34036")
        self.assertEqual(str(payload["amount"]), "169.74")


if __name__ == "__main__":
    unittest.main()
