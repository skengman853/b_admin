from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.extraction_eval import (  # noqa: E402
    _match_rows,
    aggregate_results,
)


def _case_result(**overrides) -> dict:
    base = {
        "case": "diageo_erp_statement/abc",
        "family": "diageo_erp_statement",
        "verified": True,
        "used_ai": True,
        "expected_row_count": 4,
        "extracted_row_count": 4,
        "matched_row_count": 4,
        "row_recall": 1.0,
        "row_precision": 1.0,
        "amount_exact_rate": 1.0,
        "totals_expected": 2,
        "totals_correct": 2,
        "arithmetic_mode": "activity",
        "arithmetic_status": "balanced",
        "arithmetic_delta": "0.00",
        "arithmetic_status_matches_expected": True,
    }
    base.update(overrides)
    return base


class MatchRowsTests(unittest.TestCase):
    def test_matches_rows_on_reference_and_amount(self) -> None:
        expected = [
            {"reference": "9263312263", "amount": "250.00"},
            {"reference": "DD-15-04", "amount": "100.00"},
        ]
        extracted = [
            {"reference": "9263312263", "amount": "250.00"},
            {"reference": "DD-15-04", "amount": "100.00"},
        ]
        matched, amount_exact = _match_rows(expected, extracted)
        self.assertEqual(matched, 2)
        self.assertEqual(amount_exact, 2)

    def test_reference_match_with_wrong_amount_counts_match_not_exact(self) -> None:
        expected = [{"reference": "9263312263", "amount": "250.00"}]
        extracted = [{"reference": "9263312263", "amount": "255.00"}]
        matched, amount_exact = _match_rows(expected, extracted)
        self.assertEqual(matched, 1)
        self.assertEqual(amount_exact, 0)

    def test_normalizes_leading_zeros_in_references(self) -> None:
        expected = [{"reference": "0034769", "amount": "786.50"}]
        extracted = [{"reference": "34769", "amount": "786.50"}]
        matched, amount_exact = _match_rows(expected, extracted)
        self.assertEqual(matched, 1)
        self.assertEqual(amount_exact, 1)

    def test_missed_row_is_not_matched(self) -> None:
        expected = [
            {"reference": "INV-1", "amount": "10.00"},
            {"reference": "INV-2", "amount": "20.00"},
        ]
        extracted = [{"reference": "INV-1", "amount": "10.00"}]
        matched, _ = _match_rows(expected, extracted)
        self.assertEqual(matched, 1)

    def test_each_extracted_row_matches_at_most_once(self) -> None:
        expected = [
            {"reference": "INV-1", "amount": "10.00"},
            {"reference": "INV-1", "amount": "10.00"},
        ]
        extracted = [{"reference": "INV-1", "amount": "10.00"}]
        matched, _ = _match_rows(expected, extracted)
        self.assertEqual(matched, 1)


class AggregateResultsTests(unittest.TestCase):
    def test_aggregates_per_family_metrics(self) -> None:
        summary = aggregate_results(
            [
                _case_result(),
                _case_result(
                    case="diageo_erp_statement/def",
                    row_recall=0.5,
                    row_precision=0.5,
                    amount_exact_rate=0.5,
                    totals_expected=2,
                    totals_correct=1,
                    arithmetic_status="unbalanced",
                ),
                _case_result(
                    case="trade_statement/ghi",
                    family="trade_statement",
                    arithmetic_status="insufficient_data",
                    row_recall=None,
                    row_precision=None,
                    amount_exact_rate=None,
                ),
            ]
        )

        diageo = summary["diageo_erp_statement"]
        self.assertEqual(diageo["cases"], 2)
        self.assertEqual(diageo["row_recall"], 0.75)
        self.assertEqual(diageo["control_totals_accuracy"], 0.75)
        self.assertEqual(diageo["arithmetic_balanced_rate"], 0.5)
        self.assertEqual(diageo["arithmetic_statuses"], {"balanced": 1, "unbalanced": 1})

        trade = summary["trade_statement"]
        self.assertEqual(trade["cases"], 1)
        self.assertIsNone(trade["row_recall"])
        self.assertEqual(trade["arithmetic_balanced_rate"], 0.0)
        self.assertEqual(trade["arithmetic_statuses"], {"insufficient_data": 1})


if __name__ == "__main__":
    unittest.main()
