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
)


class SupplierProfilesTests(unittest.TestCase):
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
