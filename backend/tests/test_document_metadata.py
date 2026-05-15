from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_metadata import extract_amount, extract_document_date, extract_reference  # noqa: E402


CHRIS_LYNCH_INVOICE_TEXT = """Invoice
Invoice No.: OUT-75826
Invoice Date: 23-03-26

Order Total

18/03/26
264286 E/R 14 (Open) FC €431.72 Mixed C & D Waste
13.50%
€431.72

20/03/26
264625 E/R 14 (Open) FC €431.72 Mixed C & D Waste
13.50%
€431.72

23/03/26
264768 E/R 14 (Open) FC €431.72 Bulky Waste
13.50%
€431.72

Net Total

€1,295.16

VAT

€174.84

Grand Total

Tax Code
Tax Percent
Taxable Amount
Tax Amount
T1
13.5%
1295.16
174.84

€1,470.00
"""


PROFORMA_TEXT = """PROFORMA INVOICE
PFINV-121

Order charges
Bulky Waste
€431.72

Net Total
€431.72

VAT 13.5%
€58.28

Total
€490.00

Order total
€490.00
"""


STATEMENT_TEXT = """Statement (01 April 2026 - 30 April 2026)

Date
Description
Amount
Outstanding
Status

01/04/2026
Balance Forward
0.00
0.00

24/04/2026
SI-642462 (Ref: CS )
475.47
475.47
Not Paid

30/04/2026
Total Balance
475.47
475.47
Not Paid

Total Due
475.47

Outstanding Balance
475.47
"""


AUTOMATIC_AMUSEMENTS_TEXT = """Invoice
Invoice No:
112017
Invoice Date:
03/05/2026

Total Net Amount
80.00

Total VAT Amount
18.40

Invoice Total
98.40
"""


AUTOMATIC_AMUSEMENTS_SECOND_ATTACHMENT_TEXT = """Invoice
Invoice No:
112020
Invoice Date:
03/05/2026

Invoice Total
98.40
"""


RAILWAY_RECEIPT_TEXT = """Receipt
Invoice number UIMSS74R-0003
Receipt number 2277-2700
Date paid
April 25, 2026

Amount paid
$5.00
"""


RAILWAY_INVOICE_TEXT = """Invoice
Invoice number UIMSS74R-0003
Date of issue
April 25, 2026

Amount due
$5.00 USD
"""


RENDER_INVOICE_TEXT = """Invoice
Invoice number
Date of issue
Date due

NDSIRW9S-0003
May 5, 2026
May 5, 2026

Amount due
$7.25 USD
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

Paid
€397.25

Balance Due
€0.00
"""


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

Tax Code
Tax Percent
Taxable Amount
Tax Amount
T1
13.5%
431.72
58.28
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


BULMERS_STATEMENT_TEXT = """Customer Statement,1001,,,,31/12/16,113480.60,,,,,,00060~CCCS_2017004_132705.TXT

STATEMENT

Issued by
Bulmers Ireland

CANAL TURN
T/A THE CANAL TURN
Main Street
Ballymahon

Statement Date

30/04/26
"""

BULMERS_INVOICE_TEXT = """INVOICE,9890200,9890201,1466,60008348,12/12/16,2205.36,273263,15/12/16,60009694,,,00060~CCCI_2016347_225404.TXT

Issued by
Bulmers Ireland

INVOICE

Invoice Number

4150707

Delivery Date

15/04/26

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
"""


class ExtractAmountTests(unittest.TestCase):
    def test_prefers_grand_total_over_order_total_header(self) -> None:
        self.assertEqual(extract_amount(CHRIS_LYNCH_INVOICE_TEXT, "invoice"), "1470.00")

    def test_extracts_proforma_total(self) -> None:
        self.assertEqual(extract_amount(PROFORMA_TEXT, "invoice"), "490.00")

    def test_extracts_statement_balance(self) -> None:
        self.assertEqual(extract_amount(STATEMENT_TEXT, "statement"), "475.47")

    def test_extracts_invoice_total(self) -> None:
        self.assertEqual(extract_amount(AUTOMATIC_AMUSEMENTS_TEXT, "invoice"), "98.40")

    def test_extracts_receipt_amount_paid(self) -> None:
        self.assertEqual(extract_amount(RAILWAY_RECEIPT_TEXT, "receipt"), "5.00")

    def test_prefers_total_over_zero_balance_due(self) -> None:
        self.assertEqual(extract_amount(DAVID_CAMPBELL_INVOICE_TEXT, "invoice"), "397.25")

    def test_extracts_grand_total_for_short_invoice_layout(self) -> None:
        self.assertEqual(extract_amount(CHRIS_LYNCH_SHORT_INVOICE_TEXT, "invoice"), "490.00")

    def test_skips_total_column_headers_and_uses_summary_total(self) -> None:
        self.assertEqual(extract_amount(LOVELL_MULTI_INVOICE_TEXT, "invoice"), "367.24")

    def test_extracts_us_style_date_for_david_campbell_template(self) -> None:
        self.assertEqual(extract_document_date(DAVID_CAMPBELL_INVOICE_TEXT), "2026-04-23")

    def test_prefers_labeled_statement_date_over_legacy_export_date(self) -> None:
        self.assertEqual(
            extract_document_date(
                BULMERS_STATEMENT_TEXT,
                "Bulmers Ireland/Statements/Careys Bar/Bulmers Ireland - Stmt 018 - Date 30-04-2026 - Linked.pdf",
            ),
            "2026-04-30",
        )

    def test_prefers_attachment_date_over_export_header_for_archive_invoice(self) -> None:
        self.assertEqual(
            extract_document_date(
                BULMERS_INVOICE_TEXT,
                "Bulmers Ireland/Invoices/Careys Bar/Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026 - Linked.pdf",
                "Careys Bar - Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026.pdf",
            ),
            "2026-04-15",
        )

    def test_extracts_archive_invoice_reference_from_filename(self) -> None:
        self.assertEqual(
            extract_reference(
                BULMERS_INVOICE_TEXT,
                "Bulmers Ireland/Invoices/Careys Bar/Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026 - Linked.pdf",
                "Careys Bar - Bulmers Ireland - Inv 106 - 4150707 - Date 15-04-2026.pdf",
            ),
            "4150707",
        )

    def test_extracts_total_amount_from_archive_invoice_and_ignores_export_row(self) -> None:
        self.assertEqual(extract_amount(BULMERS_INVOICE_TEXT, "invoice"), "18.00")

    def test_prefers_receipt_reference_for_receipts(self) -> None:
        self.assertEqual(
            extract_reference(
                RAILWAY_RECEIPT_TEXT,
                "Your receipt from Railway Corporation #2277-2700",
                "Receipt-2277-2700.pdf",
            ),
            "2277-2700",
        )

    def test_prefers_invoice_reference_for_invoice_attachment_even_with_receipt_subject(self) -> None:
        self.assertEqual(
            extract_reference(
                RAILWAY_INVOICE_TEXT,
                "Your receipt from Railway Corporation #2277-2700",
                "Invoice-UIMSS74R-0003.pdf",
            ),
            "UIMSS74R-0003",
        )

    def test_uses_invoice_filename_when_text_header_would_otherwise_capture_date(self) -> None:
        self.assertEqual(
            extract_reference(
                RENDER_INVOICE_TEXT,
                "Your receipt from Render Services, Inc dba Render #2453-7030",
                "Invoice-NDSIRW9S-0003.pdf",
            ),
            "NDSIRW9S-0003",
        )

    def test_prefers_attachment_reference_over_shared_email_subject(self) -> None:
        self.assertEqual(
            extract_reference(
                AUTOMATIC_AMUSEMENTS_SECOND_ATTACHMENT_TEXT,
                "Fwd: Invoice No 112017 from Automatic Amusements",
                "Invoice 112020.pdf",
            ),
            "112020",
        )


if __name__ == "__main__":
    unittest.main()
