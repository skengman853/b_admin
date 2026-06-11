from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.supplier_profiles import (  # noqa: E402
    PARSER_FAMILY_STATEMENT_OF_ACCOUNT,
    PARSER_FAMILY_TRADE_STATEMENT,
    build_supplier_lookup_keys,
    canonicalize_supplier_name,
    detect_statement_parser_family,
    is_operator_entity,
)


class SupplierProfilesTests(unittest.TestCase):
    def test_recognizes_operator_entities_in_any_casing(self) -> None:
        self.assertTrue(is_operator_entity("Careys Bar"))
        self.assertTrue(is_operator_entity("CANAL TURN"))
        self.assertTrue(is_operator_entity("The Canal Turn"))
        self.assertTrue(is_operator_entity("CAREY'S BAR LTD"))

    def test_real_suppliers_are_not_operator_entities(self) -> None:
        self.assertFalse(is_operator_entity("Diageo"))
        self.assertFalse(is_operator_entity("Connacht Bottlers"))
        self.assertFalse(is_operator_entity(None))
        self.assertFalse(is_operator_entity("Other"))

    def test_canonicalizes_known_bank_alias(self) -> None:
        self.assertEqual(canonicalize_supplier_name("MoodMaster"), "Automatic Amusements")

    def test_canonicalizes_bulmers_ireland_alias(self) -> None:
        self.assertEqual(canonicalize_supplier_name("Bulmers Ireland"), "Bulmers")

    def test_expands_unique_truncated_supplier_prefix(self) -> None:
        keys = build_supplier_lookup_keys("LittleLuxuri")

        self.assertIn("littleluxuries", keys)

    def test_uses_profile_family_for_trade_statement_alias(self) -> None:
        family = detect_statement_parser_family(
            supplier="JJ Mahon and Sons",
            text="Monthly statement header",
        )

        self.assertEqual(family, PARSER_FAMILY_TRADE_STATEMENT)

    def test_uses_text_family_when_supplier_is_missing(self) -> None:
        family = detect_statement_parser_family(
            supplier=None,
            text="STATEMENT OF ACCOUNT\nCustomer Account No: 2016632103",
        )

        self.assertEqual(family, PARSER_FAMILY_STATEMENT_OF_ACCOUNT)


if __name__ == "__main__":
    unittest.main()
