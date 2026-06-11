from __future__ import annotations

import sys
import types
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.statement_arithmetic import (  # noqa: E402
    ARITHMETIC_BALANCED,
    ARITHMETIC_INSUFFICIENT_DATA,
    ARITHMETIC_MODE_ACTIVITY,
    ARITHMETIC_MODE_NOT_APPLICABLE,
    ARITHMETIC_MODE_OPEN_ITEM,
    ARITHMETIC_NOT_APPLICABLE,
    ARITHMETIC_UNBALANCED,
    ArithmeticRow,
    classify_statement_row_kind,
    verify_statement_arithmetic,
)

if "pydantic_settings" not in sys.modules:
    fake_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - tiny test shim
        def __init__(self, **_: object) -> None:
            pass

    fake_module.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = fake_module

_ai_import_error: str | None = None
try:
    from app.services.ai_document_extraction import (  # noqa: E402
        AIDocumentExtractionResult,
        merge_ai_extraction,
        normalize_currency_code,
    )
except Exception as exc:  # pragma: no cover - host Python may not have app deps
    _ai_import_error = str(exc)


def _row(kind: str, amount: str | None) -> ArithmeticRow:
    return ArithmeticRow(kind=kind, amount=Decimal(amount) if amount is not None else None)


class ClassifyStatementRowKindTests(unittest.TestCase):
    def test_classifies_invoice_credit_and_payment_wordings(self) -> None:
        self.assertEqual(classify_statement_row_kind("INVOIC"), "invoice")
        self.assertEqual(classify_statement_row_kind("Invoice"), "invoice")
        self.assertEqual(classify_statement_row_kind("Cr.Note"), "credit_note")
        self.assertEqual(classify_statement_row_kind("CRNOTE"), "credit_note")
        self.assertEqual(classify_statement_row_kind("PAYMNT"), "payment")
        self.assertEqual(classify_statement_row_kind("Receipt"), "payment")
        self.assertEqual(classify_statement_row_kind("DD-29-04"), "payment")

    def test_classifies_discount_rows(self) -> None:
        self.assertEqual(classify_statement_row_kind("Sett Disc"), "discount")
        self.assertEqual(classify_statement_row_kind("Settlement Discount"), "discount")

    def test_classifies_rebate_rows_as_credit(self) -> None:
        self.assertEqual(classify_statement_row_kind("REBATE"), "credit_note")

    def test_unknown_types_are_other(self) -> None:
        self.assertEqual(classify_statement_row_kind(None), "other")
        self.assertEqual(classify_statement_row_kind(""), "other")

    def test_classifies_balance_forward_rows(self) -> None:
        self.assertEqual(classify_statement_row_kind("Balance Forward"), "balance_forward")
        self.assertEqual(classify_statement_row_kind(None, reference="B/FWD"), "balance_forward")
        self.assertEqual(classify_statement_row_kind("", reference="b fwd"), "balance_forward")


class VerifyStatementArithmeticTests(unittest.TestCase):
    def test_activity_mode_balances_invoices_credits_and_payments(self) -> None:
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "250.00"),
                _row("invoice", "36.50"),
                _row("credit_note", "10.00"),
                _row("payment", "100.00"),
            ],
            opening_balance=Decimal("110.00"),
            closing_balance=Decimal("286.50"),
            total_due=None,
        )
        self.assertEqual(result.mode, ARITHMETIC_MODE_ACTIVITY)
        self.assertEqual(result.status, ARITHMETIC_BALANCED)
        self.assertEqual(result.delta, Decimal("0.00"))

    def test_activity_mode_reports_unbalanced_delta(self) -> None:
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "250.00"),
                _row("payment", "100.00"),
            ],
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("300.00"),
            total_due=None,
        )
        self.assertEqual(result.status, ARITHMETIC_UNBALANCED)
        self.assertEqual(result.delta, Decimal("-50.00"))

    def test_activity_mode_subtracts_discount_rows(self) -> None:
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "500.00"),
                _row("discount", "25.00"),
                _row("payment", "200.00"),
            ],
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("275.00"),
            total_due=None,
        )
        self.assertEqual(result.status, ARITHMETIC_BALANCED)

    def test_activity_mode_balances_zero_activity_statement(self) -> None:
        result = verify_statement_arithmetic(
            rows=[],
            opening_balance=Decimal("120.00"),
            closing_balance=Decimal("120.00"),
            total_due=None,
        )
        self.assertEqual(result.status, ARITHMETIC_BALANCED)

    def test_activity_mode_excludes_brought_forward_charges_before_period(self) -> None:
        # An invoice dated before the statement period is already inside the
        # opening balance and must not be re-added (Heineken layout).
        result = verify_statement_arithmetic(
            rows=[
                ArithmeticRow(kind="invoice", amount=Decimal("36.92"), event_date=date(2025, 11, 27)),
                ArithmeticRow(kind="payment", amount=Decimal("36.92"), event_date=date(2025, 12, 1)),
                ArithmeticRow(kind="invoice", amount=Decimal("4561.09"), event_date=date(2025, 12, 31)),
            ],
            opening_balance=Decimal("36.92"),
            closing_balance=Decimal("4561.09"),
            total_due=None,
            period_start=date(2025, 12, 1),
        )
        self.assertEqual(result.status, ARITHMETIC_BALANCED)
        self.assertIn("brought_forward_rows_excluded", result.checks)

    def test_activity_mode_ignores_balance_forward_rows(self) -> None:
        result = verify_statement_arithmetic(
            rows=[
                _row("balance_forward", "606.13"),
                _row("payment", "606.13"),
                _row("invoice", "688.97"),
            ],
            opening_balance=Decimal("606.13"),
            closing_balance=Decimal("688.97"),
            total_due=None,
        )
        self.assertEqual(result.status, ARITHMETIC_BALANCED)

    def test_activity_mode_uses_total_due_as_missing_closing_balance(self) -> None:
        # Diageo main statements state an opening balance and Total Due only.
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "2634.41"),
                _row("payment", "2634.41"),
                _row("invoice", "3898.62"),
            ],
            opening_balance=Decimal("0.00"),
            closing_balance=None,
            total_due=Decimal("3898.62"),
        )
        self.assertEqual(result.mode, ARITHMETIC_MODE_ACTIVITY)
        self.assertEqual(result.status, ARITHMETIC_BALANCED)
        self.assertIn("total_due_used_as_closing", result.checks)

    def test_open_item_mode_balances_against_total_due(self) -> None:
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "300.00"),
                _row("credit_note", "50.00"),
            ],
            opening_balance=None,
            closing_balance=None,
            total_due=Decimal("250.00"),
        )
        self.assertEqual(result.mode, ARITHMETIC_MODE_OPEN_ITEM)
        self.assertEqual(result.status, ARITHMETIC_BALANCED)

    def test_open_item_mode_nets_paid_amounts_against_items(self) -> None:
        # Per-item statements (e.g. Bulmers) list each item's amount and what was
        # paid against it; the open total is items minus payments.
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "843.69"),
                _row("payment", "843.69"),
                _row("invoice", "876.10"),
                _row("invoice", "18.00"),
            ],
            opening_balance=None,
            closing_balance=None,
            total_due=Decimal("894.10"),
        )
        self.assertEqual(result.mode, ARITHMETIC_MODE_OPEN_ITEM)
        self.assertEqual(result.status, ARITHMETIC_BALANCED)

    def test_open_item_mode_nets_negative_payment_as_credit_application(self) -> None:
        # Bulmers-style: a credit note's "paid" column shows a positive value,
        # i.e. a negative payment that cancels the credit inside the statement.
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "1576.37"),
                _row("payment", "1576.37"),
                _row("credit_note", "20.50"),
                _row("payment", "-20.50"),
                _row("invoice", "876.10"),
            ],
            opening_balance=None,
            closing_balance=None,
            total_due=Decimal("876.10"),
        )
        self.assertEqual(result.status, ARITHMETIC_BALANCED)

    def test_open_item_mode_not_used_when_closing_balance_present_without_opening(self) -> None:
        # A closing balance without an opening one means the rows are period
        # activity against an unknown starting point: unverifiable.
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "300.00"),
                _row("payment", "300.00"),
            ],
            opening_balance=None,
            closing_balance=Decimal("250.00"),
            total_due=Decimal("250.00"),
        )
        self.assertEqual(result.status, ARITHMETIC_INSUFFICIENT_DATA)

    def test_open_item_mode_allows_mirrored_closing_balance_without_payments(self) -> None:
        # BOC-style: the same outstanding figure lands in both closing_balance
        # and total_due; with no payment rows this is a plain unpaid-items list.
        result = verify_statement_arithmetic(
            rows=[_row("invoice", "73.92")],
            opening_balance=None,
            closing_balance=Decimal("73.92"),
            total_due=Decimal("73.92"),
        )
        self.assertEqual(result.mode, ARITHMETIC_MODE_OPEN_ITEM)
        self.assertEqual(result.status, ARITHMETIC_BALANCED)

    def test_closing_balance_alone_is_insufficient(self) -> None:
        result = verify_statement_arithmetic(
            rows=[_row("payment", "47.50")],
            opening_balance=None,
            closing_balance=Decimal("47.50"),
            total_due=None,
        )
        self.assertEqual(result.mode, ARITHMETIC_MODE_NOT_APPLICABLE)
        self.assertEqual(result.status, ARITHMETIC_INSUFFICIENT_DATA)

    def test_rows_missing_amounts_are_insufficient_not_unbalanced(self) -> None:
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "250.00"),
                _row("invoice", None),
            ],
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("250.00"),
            total_due=None,
        )
        self.assertEqual(result.status, ARITHMETIC_INSUFFICIENT_DATA)
        self.assertIn("rows_missing_amounts", result.checks)

    def test_unclassified_rows_with_amounts_are_insufficient(self) -> None:
        result = verify_statement_arithmetic(
            rows=[
                _row("invoice", "250.00"),
                _row("other", "99.00"),
            ],
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("250.00"),
            total_due=None,
        )
        self.assertEqual(result.status, ARITHMETIC_INSUFFICIENT_DATA)
        self.assertIn("unclassified_rows_with_amounts", result.checks)

    def test_exempt_statement_kinds_are_not_applicable(self) -> None:
        for statement_kind in (
            "keg_flow_statement",
            "sub_account_statement",
            "sub_account",
            "Sub Account Statement",
            "keg-flow",
        ):
            result = verify_statement_arithmetic(
                rows=[],
                opening_balance=Decimal("0.00"),
                closing_balance=Decimal("10.00"),
                total_due=None,
                statement_kind=statement_kind,
            )
            self.assertEqual(result.status, ARITHMETIC_NOT_APPLICABLE)

    def test_records_total_due_discount_consistency_check(self) -> None:
        result = verify_statement_arithmetic(
            rows=[_row("invoice", "525.00")],
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("525.00"),
            total_due=Decimal("500.00"),
            settlement_discount_total=Decimal("25.00"),
        )
        self.assertEqual(result.status, ARITHMETIC_BALANCED)
        self.assertIn("total_due_matches_closing_minus_discount", result.checks)

    def test_tolerates_one_cent_rounding(self) -> None:
        result = verify_statement_arithmetic(
            rows=[_row("invoice", "100.01")],
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("100.00"),
            total_due=None,
        )
        self.assertEqual(result.status, ARITHMETIC_BALANCED)


@unittest.skipIf(_ai_import_error is not None, f"AI extraction helper unavailable: {_ai_import_error}")
class NormalizeCurrencyCodeTests(unittest.TestCase):
    def test_maps_currency_names_to_iso_codes(self) -> None:
        self.assertEqual(normalize_currency_code("Euro"), "EUR")
        self.assertEqual(normalize_currency_code("euros"), "EUR")
        self.assertEqual(normalize_currency_code("€"), "EUR")
        self.assertEqual(normalize_currency_code("Sterling"), "GBP")

    def test_passes_through_iso_codes_uppercased(self) -> None:
        self.assertEqual(normalize_currency_code("eur"), "EUR")
        self.assertEqual(normalize_currency_code("GBP"), "GBP")

    def test_unmappable_values_become_none(self) -> None:
        self.assertIsNone(normalize_currency_code(None))
        self.assertIsNone(normalize_currency_code(""))
        self.assertIsNone(normalize_currency_code("Irish Punt"))

    def test_ai_result_normalizes_currency_field(self) -> None:
        result = AIDocumentExtractionResult(currency="Euro")
        self.assertEqual(result.currency, "EUR")


@unittest.skipIf(_ai_import_error is not None, f"AI extraction helper unavailable: {_ai_import_error}")
class StatementQualityArithmeticTests(unittest.TestCase):
    def _document(self):
        return types.SimpleNamespace(
            document_type="statement",
            supplier="Heineken",
            attachment_name="heineken_statement.pdf",
            source_email_subject="Heineken statement of account",
            ai_extraction_status=None,
            ai_extraction_provider=None,
            ai_extraction_model=None,
            ai_extraction_payload=None,
            ai_extracted_at=None,
        )

    def _base_fields(self) -> dict:
        return {
            "document_date": None,
            "reference": None,
            "amount": None,
            "vat_amount": None,
            "currency": None,
            "confidence_score": 0.4,
            "review_reasons": [],
            "needs_review": False,
            "extraction_status": "review",
        }

    def test_balanced_statement_is_promoted_with_high_confidence(self) -> None:
        ai_result = AIDocumentExtractionResult(
            document_date="2026-04-30",
            statement_kind="supplier_statement",
            is_financial=True,
            period_start="2026-04-01",
            period_end="2026-04-30",
            opening_balance="110.00",
            closing_balance="286.50",
            confidence_score=0.75,
            entries=[
                {"reference": "INV-1", "transaction_type": "Invoice", "amount": "250.00"},
                {"reference": "INV-2", "transaction_type": "Invoice", "amount": "36.50"},
                {"reference": "CR-1", "transaction_type": "Cr.Note", "amount": "10.00"},
                {"reference": "DD-15-04", "transaction_type": "Receipt", "amount": "100.00"},
            ],
        )

        merged = merge_ai_extraction(
            document=self._document(),
            extraction_fields=self._base_fields(),
            ai_result=ai_result,
        )

        self.assertGreaterEqual(merged["confidence_score"], 0.9)
        self.assertEqual(merged["extraction_status"], "extracted")
        self.assertFalse(merged["needs_review"])
        self.assertNotIn("statement_unbalanced", merged["review_reasons"])

    def test_unbalanced_statement_is_flagged_for_review(self) -> None:
        ai_result = AIDocumentExtractionResult(
            document_date="2026-04-30",
            statement_kind="supplier_statement",
            is_financial=True,
            period_start="2026-04-01",
            period_end="2026-04-30",
            opening_balance="100.00",
            closing_balance="300.00",
            confidence_score=0.85,
            entries=[
                {"reference": "INV-1", "transaction_type": "Invoice", "amount": "250.00"},
                {"reference": "DD-15-04", "transaction_type": "Receipt", "amount": "100.00"},
            ],
        )

        merged = merge_ai_extraction(
            document=self._document(),
            extraction_fields=self._base_fields(),
            ai_result=ai_result,
        )

        self.assertIn("statement_unbalanced", merged["review_reasons"])
        self.assertLessEqual(merged["confidence_score"], 0.55)
        self.assertEqual(merged["extraction_status"], "review")
        self.assertTrue(merged["needs_review"])


if __name__ == "__main__":
    unittest.main()
