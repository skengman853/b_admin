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

_missing_dependencies: str | None = None

try:
    from app.models import Document, DocumentFinancialRow, ReconciliationSuggestion, ReconciliationSuggestionItem, Transaction  # noqa: E402
    from app.services.reconciliation_suggestions import _apply_deterministic_verifier  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class ReconciliationSuggestionVerifierTests(unittest.TestCase):
        @unittest.skip(f"reconciliation suggestion tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class ReconciliationSuggestionVerifierTests(unittest.TestCase):
        def _transaction(self, amount: str) -> Transaction:
            return Transaction(
                user_id=uuid.uuid4(),
                source_type="bank_statement",
                source_file="bank/sample.pdf",
                source_sheet="sheet",
                row_number=1,
                transaction_date=date(2026, 4, 2),
                description1="Example Supplier",
                debit_amount=Decimal(amount),
                transaction_type="Debit",
                raw_row_json={},
            )

        def _document(self, *, document_type: str, amount: str, reference: str) -> Document:
            return Document(
                id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                gmail_message_id=f"msg-{reference}",
                attachment_index=0,
                attachment_name=f"{reference}.pdf",
                supplier="Example Supplier",
                document_type=document_type,
                document_date=date(2026, 4, 1),
                reference=reference,
                amount=Decimal(amount),
                extraction_status="extracted",
                local_path=f"Documents/{reference}.pdf",
                needs_review=False,
                review_reasons=[],
            )

        def _row(self, *, document: Document, row_type: str, amount: str, signed_amount: str, reference: str) -> DocumentFinancialRow:
            return DocumentFinancialRow(
                id=uuid.uuid4(),
                user_id=document.user_id,
                document_id=document.id,
                extraction_run_id=uuid.uuid4(),
                row_index=0,
                row_type=row_type,
                reference=reference,
                amount=Decimal(amount),
                signed_amount=Decimal(signed_amount),
                is_financial=True,
            )

        def test_direct_invoice_match_verifier_passes_on_exact_sum(self) -> None:
            transaction = self._transaction("100.00")
            invoice = self._document(document_type="invoice", amount="100.00", reference="INV100")
            row = self._row(document=invoice, row_type="invoice", amount="100.00", signed_amount="100.00", reference="INV100")
            suggestion = ReconciliationSuggestion(
                user_id=transaction.user_id,
                transaction_id=transaction.id,
                suggestion_type="direct_invoice_match",
                status="suggested",
                reason_json={},
                matcher_version="test",
            )
            suggestion.items = [
                ReconciliationSuggestionItem(
                    user_id=transaction.user_id,
                    document_id=invoice.id,
                    financial_row_id=row.id,
                    item_role="invoice_exact",
                    reference="INV100",
                    amount=Decimal("100.00"),
                    signed_amount=Decimal("100.00"),
                )
            ]

            _apply_deterministic_verifier(
                transaction=transaction,
                suggestion=suggestion,
                document_by_id={invoice.id: invoice},
                financial_row_by_id={row.id: row},
            )

            self.assertEqual(suggestion.verifier_status, "passed")
            self.assertEqual(
                suggestion.reason_json["verifier_reasons"],
                ["Exact invoice or credit components sum to the bank amount."],
            )

        def test_statement_settlement_verifier_passes_on_payment_and_components(self) -> None:
            transaction = self._transaction("250.00")
            statement = self._document(document_type="statement", amount="0.00", reference="STMT1")
            payment_row = self._row(document=statement, row_type="payment", amount="250.00", signed_amount="250.00", reference="DD-01")
            invoice_row = self._row(document=statement, row_type="invoice", amount="250.00", signed_amount="250.00", reference="INV250")
            suggestion = ReconciliationSuggestion(
                user_id=transaction.user_id,
                transaction_id=transaction.id,
                suggestion_type="statement_settlement",
                status="suggested",
                reason_json={},
                matcher_version="test",
            )
            suggestion.items = [
                ReconciliationSuggestionItem(
                    user_id=transaction.user_id,
                    document_id=statement.id,
                    financial_row_id=payment_row.id,
                    item_role="payment_row",
                    reference="DD-01",
                    amount=Decimal("250.00"),
                    signed_amount=Decimal("250.00"),
                ),
                ReconciliationSuggestionItem(
                    user_id=transaction.user_id,
                    document_id=statement.id,
                    financial_row_id=invoice_row.id,
                    item_role="invoice",
                    reference="INV250",
                    amount=Decimal("250.00"),
                    signed_amount=Decimal("250.00"),
                ),
            ]

            _apply_deterministic_verifier(
                transaction=transaction,
                suggestion=suggestion,
                document_by_id={statement.id: statement},
                financial_row_by_id={payment_row.id: payment_row, invoice_row.id: invoice_row},
            )

            self.assertEqual(suggestion.verifier_status, "passed")
            self.assertEqual(
                suggestion.reason_json["verifier_reasons"],
                ["A stored statement payment row matches the bank amount and has linked invoice or credit components."],
            )

        def test_supporting_docs_only_verifier_stays_partial(self) -> None:
            transaction = self._transaction("99.99")
            statement = self._document(document_type="statement", amount="0.00", reference="STMT2")
            suggestion = ReconciliationSuggestion(
                user_id=transaction.user_id,
                transaction_id=transaction.id,
                suggestion_type="supporting_docs_only",
                status="suggested",
                reason_json={},
                matcher_version="test",
            )
            suggestion.items = [
                ReconciliationSuggestionItem(
                    user_id=transaction.user_id,
                    document_id=statement.id,
                    item_role="statement",
                    reference="STMT2",
                )
            ]

            _apply_deterministic_verifier(
                transaction=transaction,
                suggestion=suggestion,
                document_by_id={statement.id: statement},
                financial_row_by_id={},
            )

            self.assertEqual(suggestion.verifier_status, "partial")
            self.assertEqual(
                suggestion.reason_json["verifier_reasons"],
                ["Supporting documents are present, but no deterministic settlement group was verified."],
            )


if __name__ == "__main__":
    unittest.main()
