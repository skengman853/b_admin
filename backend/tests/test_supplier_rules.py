from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.supplier_rules import detect_supplier  # noqa: E402


class SupplierRulesTests(unittest.TestCase):
    def test_render_subject_strips_receipt_number_from_supplier_name(self) -> None:
        self.assertEqual(
            detect_supplier(
                '"Render Services, Inc dba Render" <invoice+statements@render.com>',
                "Your receipt from Render Services, Inc dba Render #2453-7030",
                "",
                "Receipt-2453-7030.pdf",
                "",
            ),
            "Render Services, Inc dba Render",
        )

    def test_trading_as_subject_prefers_business_name(self) -> None:
        self.assertEqual(
            detect_supplier(
                "david campbell <davidmartincampbell@live.ie>",
                "PAID: Invoice 262 · David Campbell t/a little luxuries",
                "",
                "invoice_262.pdf",
                "",
            ),
            "Little Luxuries",
        )

    def test_pub_name_in_subject_is_not_attributed_as_supplier(self) -> None:
        self.assertEqual(
            detect_supplier(
                "",
                "Careys Bar statement May 2025",
                "",
                "statement.pdf",
                "",
            ),
            "Other",
        )

    def test_pub_trading_name_in_pdf_text_is_not_attributed_as_supplier(self) -> None:
        self.assertEqual(
            detect_supplier(
                "",
                "Sub Account Statements TCT003",
                "Invoice Address\nCAREY'S BAR LTD\nT/A THE CANAL TURN\nMAIN STREET",
                "statement.pdf",
                "",
            ),
            "Other",
        )

    def test_supplier_in_pdf_text_wins_over_pub_customer_address(self) -> None:
        self.assertEqual(
            detect_supplier(
                "",
                "Sub Account Statements TCT003",
                "SUB ACCOUNT STATEMENT\nDiageo Ireland\nInvoice Address\nCAREY'S BAR LTD\nT/A THE CANAL TURN",
                "statement.pdf",
                "",
            ),
            "Diageo",
        )

    def test_no_reply_sender_without_other_signals_falls_back_to_other(self) -> None:
        self.assertEqual(
            detect_supplier(
                "Waste Logics no-reply <noreply@wastelogics.com>",
                "Proforma Invoice PFINV-121",
                "",
                "Proforma Invoice PFINV-121 for order 270092.pdf",
                "",
            ),
            "Other",
        )


if __name__ == "__main__":
    unittest.main()
