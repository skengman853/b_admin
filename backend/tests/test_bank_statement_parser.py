from __future__ import annotations

import sys
import types
import unittest
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
    from app.services.bank_statement_parser import (  # noqa: E402
        ParsedBankStatementLine,
        parse_aib_bank_statement_lines,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class BankStatementParserTests(unittest.TestCase):
        @unittest.skip(f"bank statement parser tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class BankStatementParserTests(unittest.TestCase):
        def test_parses_aib_statement_lines_into_transactions(self) -> None:
            parsed = parse_aib_bank_statement_lines(
                statement_path="backend/bankstatements/sample.pdf",
                account_name="CAREY'S BAR LTD",
                account_number="53747-031",
                sort_code="93-22-64",
                lines=[
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text="9 Apr 2026",
                        detail_text="BALANCE FORWARD",
                        debit_text=None,
                        credit_text=None,
                        balance_text="97557.10",
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text="10 Apr 2026",
                        detail_text="Interest Rate",
                        debit_text=None,
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="Lending @ 7.850%",
                        debit_text=None,
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="PAYMENTSENSE IRELA",
                        debit_text=None,
                        credit_text="554.50",
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="IE26041095386660",
                        debit_text=None,
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="TxnDate: 10Apr2026",
                        debit_text=None,
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="BOIPA1004158743491",
                        debit_text="55.00",
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="IE26041054760677",
                        debit_text=None,
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="D/D GC RE DOJOEURO",
                        debit_text="546.28",
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="IE26040952973365",
                        debit_text=None,
                        credit_text=None,
                        balance_text="90419.31",
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text="13 Apr 2026",
                        detail_text="PAYMENTSENSE IRELA",
                        debit_text=None,
                        credit_text="1391.50",
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="IE26041396264569",
                        debit_text=None,
                        credit_text=None,
                        balance_text=None,
                    ),
                    ParsedBankStatementLine(
                        page_number=1,
                        date_text=None,
                        detail_text="TxnDate: 11Apr2026",
                        debit_text=None,
                        credit_text=None,
                        balance_text="93359.81",
                    ),
                ],
            )

            self.assertEqual(parsed.provider, "aib")
            self.assertEqual(parsed.account_number, "53747-031")
            self.assertEqual(parsed.sort_code, "93-22-64")
            self.assertEqual(parsed.pub, "Careys")
            self.assertEqual(len(parsed.transactions), 4)

            first = parsed.transactions[0]
            self.assertEqual(first.row_number, 1)
            self.assertEqual(first.transaction_date, date(2026, 4, 10))
            self.assertEqual(first.detail, "PAYMENTSENSE IRELA")
            self.assertIsNone(first.debit_amount)
            self.assertEqual(first.credit_amount, Decimal("554.50"))
            self.assertEqual(first.references, ["IE26041095386660"])
            self.assertEqual(first.transaction_posted_date, date(2026, 4, 10))

            third = parsed.transactions[2]
            self.assertEqual(third.detail, "D/D GC RE DOJOEURO")
            self.assertEqual(third.debit_amount, Decimal("546.28"))
            self.assertEqual(third.balance, Decimal("90419.31"))
            self.assertEqual(third.references, ["IE26040952973365"])

            fourth = parsed.transactions[3]
            self.assertEqual(fourth.transaction_date, date(2026, 4, 13))
            self.assertEqual(fourth.credit_amount, Decimal("1391.50"))
            self.assertEqual(fourth.transaction_posted_date, date(2026, 4, 11))
            self.assertEqual(fourth.balance, Decimal("93359.81"))


if __name__ == "__main__":
    unittest.main()
