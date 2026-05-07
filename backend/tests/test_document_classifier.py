from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_classifier import classify_document_type, document_type_folder  # noqa: E402


RAILWAY_RECEIPT_TEXT = """Receipt
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


class DocumentClassifierTests(unittest.TestCase):
    def test_classifies_receipts(self) -> None:
        self.assertEqual(
            classify_document_type(
                "Your receipt from Railway Corporation #2277-2700",
                "Receipt-2277-2700.pdf",
                RAILWAY_RECEIPT_TEXT,
            ),
            "receipt",
        )

    def test_receipts_use_receipts_folder(self) -> None:
        self.assertEqual(document_type_folder("receipt"), "Receipts")

    def test_invoice_attachment_stays_invoice_even_with_receipt_subject(self) -> None:
        self.assertEqual(
            classify_document_type(
                "Your receipt from Railway Corporation #2277-2700",
                "Invoice-UIMSS74R-0003.pdf",
                RAILWAY_INVOICE_TEXT,
            ),
            "invoice",
        )


if __name__ == "__main__":
    unittest.main()
