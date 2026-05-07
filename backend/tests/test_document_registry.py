from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pydantic_settings" not in sys.modules:
    fake_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - tiny test shim
        def __init__(self, **_: object) -> None:
            pass

    fake_module.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = fake_module

from app.services.document_serialization import normalize_document_record  # noqa: E402


class DocumentRegistryTests(unittest.TestCase):
    def test_normalize_document_record_parses_date_amount_and_review_state(self) -> None:
        payload = normalize_document_record(
            gmail_message_id="message-1",
            attachment_index=2,
            source_email_sender="supplier@example.com",
            source_email_subject="Invoice 1001",
            source_received_at=datetime(2026, 5, 7, 12, 0, 0),
            stored_file={
                "attachment_name": "invoice-1001.pdf",
                "supplier": "Supplier One",
                "document_type": "invoice",
                "document_date": "2026-05-06",
                "reference": "1001",
                "amount": "397.25",
                "needs_review": True,
                "review_reasons": ["unknown_supplier"],
                "saved_path": "Documents/Supplier One/Invoices/2026-05-06_supplier_one_invoice_1001_397_25.pdf",
            },
        )

        self.assertEqual(payload["gmail_message_id"], "message-1")
        self.assertEqual(payload["attachment_index"], 2)
        self.assertEqual(str(payload["document_date"]), "2026-05-06")
        self.assertEqual(str(payload["amount"]), "397.25")
        self.assertTrue(payload["needs_review"])
        self.assertEqual(payload["review_reasons"], ["unknown_supplier"])
        self.assertEqual(payload["source_email_subject"], "Invoice 1001")

    def test_normalize_document_record_strips_timezone_from_received_at(self) -> None:
        payload = normalize_document_record(
            gmail_message_id="message-1",
            attachment_index=0,
            source_email_sender="supplier@example.com",
            source_email_subject="Invoice 1001",
            source_received_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
            stored_file={
                "attachment_name": "invoice-1001.pdf",
                "supplier": "Supplier One",
                "document_type": "invoice",
                "document_date": "2026-05-06",
                "reference": "1001",
                "amount": "397.25",
                "needs_review": False,
                "review_reasons": [],
                "saved_path": "Documents/Supplier One/Invoices/file.pdf",
            },
        )

        self.assertEqual(payload["source_received_at"], datetime(2026, 5, 7, 12, 0, 0))


if __name__ == "__main__":
    unittest.main()
