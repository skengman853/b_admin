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

_missing: str | None = None
try:
    from app.models import Transaction  # noqa: E402
    from app.services.vat_categorisation import (  # noqa: E402
        build_vat_book,
        derive_nonresale_band,
        learn_ruleset,
        normalize_description,
        predict,
    )
    from decimal import Decimal as D
except ModuleNotFoundError as exc:  # pragma: no cover
    _missing = str(exc)


def _txn(desc, pub, category=None, debit=None, **bands):
    return Transaction(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        source_type="vatbook",
        source_file="x",
        source_sheet="s",
        row_number=1,
        pub=pub,
        transaction_date=date(2026, 4, 1),
        description1=desc,
        debit_amount=Decimal(debit) if debit else None,
        category=category,
        resale_23_amount=Decimal(bands["r23"]) if "r23" in bands else None,
        non_resale_23_amount=Decimal(bands["nr23"]) if "nr23" in bands else None,
        non_resale_13_5_amount=Decimal(bands["nr135"]) if "nr135" in bands else None,
        non_resale_9_amount=None,
        non_resale_0_amount=Decimal(bands["nr0"]) if "nr0" in bands else None,
        annotation_types=[],
        annotation_notes=[],
        has_linked_annotation=False,
    )


@unittest.skipIf(_missing is not None, f"requires app deps: {_missing}")
class NormalizeTests(unittest.TestCase):
    def test_strips_prefixes_digits_and_pub_noise(self) -> None:
        self.assertEqual(normalize_description("D/D DIAGEO IRELAND IE26040245"), normalize_description("D/D DIAGEO IRELAND"))
        self.assertEqual(normalize_description("*INET BrianCour"), "BRIANCOUR")


@unittest.skipIf(_missing is not None, f"requires app deps: {_missing}")
class RulesetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.training = [
            _txn("D/D DIAGEO IRELAND IE1", "Careys", "Resale - Diageo - Careys", "5824.90", r23="5824.90"),
            _txn("D/D DIAGEO IRELAND IE2", "Careys", "Resale - Diageo - Careys", "4027.43", r23="4027.43"),
            _txn("D/D DIAGEO IRELAND IE3", "Canal", "Resale - Diageo - Canal", "1000.00", r23="1000.00"),
            _txn("D/D BORD GAIS", "Careys", "Electricity", "200.00", nr135="200.00"),
            _txn("INSURANCE CO", "Careys", "Insurance - Pub", "300.00", nr0="300.00"),
        ]
        self.ruleset = learn_ruleset(self.training)

    def test_learns_description_and_band(self) -> None:
        diageo = _txn("D/D DIAGEO IRELAND IE9", "Careys")
        p = predict(diageo, self.ruleset)
        self.assertEqual(p.category, "Resale - Diageo - Careys")
        self.assertEqual(p.band, "resale_23")
        self.assertEqual(p.source, "learned_rule")

    def test_pub_separates_same_supplier(self) -> None:
        canal = _txn("D/D DIAGEO IRELAND IE9", "Canal")
        self.assertEqual(predict(canal, self.ruleset).category, "Resale - Diageo - Canal")

    def test_unknown_payee_returns_unknown(self) -> None:
        p = predict(_txn("*INET NewStaffMember", "Careys"), self.ruleset)
        self.assertIsNone(p.category)
        self.assertEqual(p.source, "unknown")

    def test_matched_supplier_drives_resale(self) -> None:
        # description gives no rule, but a matched Diageo document does
        mystery = _txn("UNCLEAR PAYEE REF", "Careys")
        p = predict(mystery, self.ruleset, matched_supplier="Diageo")
        self.assertEqual(p.category, "Resale - Diageo - Careys")
        self.assertEqual(p.source, "matched_supplier")

    def test_build_vat_book_scores_against_ground_truth(self) -> None:
        targets = [
            _txn("D/D DIAGEO IRELAND IE5", "Careys", "Resale - Diageo - Careys", "100.00", r23="100.00"),
            _txn("*INET Unseen", "Careys", "Some New Category", "50.00", nr23="50.00"),
        ]
        rows = build_vat_book(targets=targets, ruleset=self.ruleset)
        self.assertTrue(rows[0].category_correct)
        self.assertEqual(rows[1].source, "unknown")
        self.assertFalse(rows[1].category_correct)


@unittest.skipIf(_missing is not None, f"requires app deps: {_missing}")
class DeriveBandTests(unittest.TestCase):
    def test_derives_standard_rates(self) -> None:
        self.assertEqual(derive_nonresale_band(D("123.00"), D("23.00")), "non_resale_23")
        self.assertEqual(derive_nonresale_band(D("113.50"), D("13.50")), "non_resale_13_5")
        self.assertEqual(derive_nonresale_band(D("109.00"), D("9.00")), "non_resale_9")
        self.assertEqual(derive_nonresale_band(D("100.00"), D("0.00")), "non_resale_0")

    def test_picks_nearest_for_messy_numbers(self) -> None:
        # 13.4% effective -> 13.5 band
        self.assertEqual(derive_nonresale_band(D("226.80"), D("26.80")), "non_resale_13_5")

    def test_none_when_data_missing(self) -> None:
        self.assertIsNone(derive_nonresale_band(None, D("23")))
        self.assertIsNone(derive_nonresale_band(D("100"), None))


@unittest.skipIf(_missing is not None, f"requires app deps: {_missing}")
class BandFromInvoiceTests(unittest.TestCase):
    def test_matched_invoice_overrides_category_default_band(self) -> None:
        # train: "Renovation" usually 23%
        training = [_txn("BUILDER A", "Careys", "Renovation", "1000", nr23="1000")]
        ruleset = learn_ruleset(training)
        # a Renovation transaction whose matched invoice is actually 13.5%
        target = _txn("BUILDER A", "Careys", "Renovation", "227.00", nr135="227.00")
        rows = build_vat_book(
            targets=[target],
            ruleset=ruleset,
            document_vat_by_transaction={target.id: (D("227.00"), D("27.00"))},
        )
        self.assertEqual(rows[0].predicted_band, "non_resale_13_5")
        self.assertEqual(rows[0].band_source, "matched_invoice")

    def test_resale_band_not_overridden(self) -> None:
        training = [_txn("D/D DIAGEO IRELAND", "Careys", "Resale - Diageo - Careys", "100", r23="100")]
        ruleset = learn_ruleset(training)
        target = _txn("D/D DIAGEO IRELAND", "Careys")
        rows = build_vat_book(
            targets=[target],
            ruleset=ruleset,
            document_vat_by_transaction={target.id: (D("100"), D("0"))},  # would imply 0% if applied
        )
        self.assertEqual(rows[0].predicted_band, "resale_23")
        self.assertEqual(rows[0].band_source, "category_default")


if __name__ == "__main__":
    unittest.main()
