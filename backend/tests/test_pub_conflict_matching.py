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
    from app.models import Document, Transaction  # noqa: E402
    from app.services.document_ledger import build_document_ledgers  # noqa: E402
    from app.services.transaction_reconciliation import (  # noqa: E402
        _find_exact_matches,
        _find_suggested_matches,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


CANAL_INVOICE_TEXT = """HEINEKEN Ireland Sales Ltd.
INVOICE
Invoice Number
194149047
Invoice to:
The Canal Turn
Careys Bar Limited
Main Street
Ballymahon
Co Longford N39 WR64
Total
2,636.35
"""

CAREYS_INVOICE_TEXT = """HEINEKEN Ireland Sales Ltd.
INVOICE
Invoice Number
194159926
Invoice to:
Careys Pub
Maye Carey
38 Mardyke Street
Athlone N37 AP95
Total
2,636.35
"""


def _invoice(reference: str, text: str, event_date: date) -> "Document":
    return Document(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        gmail_message_id=f"pub-test-{reference}",
        attachment_index=0,
        derivation_index=0,
        attachment_name=f"heineken_{reference}.pdf",
        supplier="Heineken",
        document_type="invoice",
        document_date=event_date,
        reference=reference,
        amount=Decimal("2636.35"),
        extraction_status="extracted",
        extracted_text=text,
    )


def _vatbook_transaction(pub: str, transaction_date: date) -> "Transaction":
    return Transaction(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        source_type="vatbook",
        source_file="vatbook/test.xlsx",
        source_sheet="sheet",
        row_number=1,
        pub=pub,
        transaction_date=transaction_date,
        description1="D/D HEINEKEN IRELAND",
        debit_amount=Decimal("2636.35"),
        annotation_types=[],
        annotation_notes=[],
        has_linked_annotation=False,
    )


if _missing_dependencies:

    class PubConflictMatchingTests(unittest.TestCase):
        @unittest.skip(f"requires app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass

else:

    class PubConflictMatchingTests(unittest.TestCase):
        """Two pubs, one company: a document naming the other pub must never be
        suggested, even for vatbook transactions (which carry operator pubs)."""

        def setUp(self) -> None:
            self.canal_invoice = _invoice("194149047", CANAL_INVOICE_TEXT, date(2026, 4, 7))
            self.careys_invoice = _invoice("194159926", CAREYS_INVOICE_TEXT, date(2026, 4, 15))
            self.documents = [self.canal_invoice, self.careys_invoice]
            self.ledgers = build_document_ledgers(self.documents, allow_parse_fallback=True)

        def _suggested_references(self, pub: str, transaction_date: date) -> set[str]:
            matches = _find_suggested_matches(
                transaction=_vatbook_transaction(pub, transaction_date),
                documents=self.documents,
                document_ledgers=self.ledgers,
            )
            return {match.reference for match in matches}

        def test_canal_vatbook_transaction_only_suggests_canal_invoice(self) -> None:
            references = self._suggested_references("Canal", date(2026, 4, 13))
            self.assertIn("194149047", references)
            self.assertNotIn("194159926", references)

        def test_careys_vatbook_transaction_only_suggests_careys_invoice(self) -> None:
            references = self._suggested_references("Careys", date(2026, 4, 20))
            self.assertIn("194159926", references)
            self.assertNotIn("194149047", references)

    class AnnotationReferenceSupplierGuardTests(unittest.TestCase):
        """Archive filenames embed counters ("Diageo Inv - 262 - …") that must
        not claim another supplier's short invoice reference."""

        def test_reference_in_other_suppliers_filename_does_not_match(self) -> None:
            transaction = _vatbook_transaction("Careys", date(2026, 4, 2))
            transaction.annotation_notes = [
                "Invoice - Diageo Inv - 262 - Invoice Number - 9263305332 - Date - 26-03-2026.pdf"
            ]
            diageo_invoice = _invoice("9263305332", "Diageo invoice text", date(2026, 3, 26))
            diageo_invoice.supplier = "Diageo"
            little_luxuries_invoice = _invoice("262", "Little Luxuries invoice text", date(2026, 4, 23))
            little_luxuries_invoice.supplier = "Little Luxuries"

            matches = _find_exact_matches(
                transaction=transaction,
                documents=[diageo_invoice, little_luxuries_invoice],
            )

            references = {match.reference for match in matches}
            self.assertIn("9263305332", references)
            self.assertNotIn("262", references)

        def test_reference_in_neutral_note_still_matches(self) -> None:
            transaction = _vatbook_transaction("Careys", date(2026, 4, 2))
            transaction.annotation_notes = ["paid against inv 262"]
            little_luxuries_invoice = _invoice("262", "Little Luxuries invoice text", date(2026, 4, 23))
            little_luxuries_invoice.supplier = "Little Luxuries"

            matches = _find_exact_matches(
                transaction=transaction,
                documents=[little_luxuries_invoice],
            )

            self.assertEqual({match.reference for match in matches}, {"262"})


if __name__ == "__main__":
    unittest.main()
