from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pydantic_settings" not in sys.modules:
    fake_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - tiny test shim
        def __init__(self, **_: object) -> None:
            pass

    fake_module.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = fake_module

from app.config import settings
from app.services.tracking import build_review_queue, build_tracking_summary, record_processed_message


class TrackingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_data_root = settings.data_root
        settings.data_root = str(Path(self._tmpdir.name) / "data")

    def tearDown(self) -> None:
        settings.data_root = self._original_data_root
        self._tmpdir.cleanup()

    def test_build_tracking_summary_and_review_queue(self) -> None:
        record_processed_message(
            "user-1",
            "message-1",
            {
                "status": "processed",
                "sender": "sender@example.com",
                "subject": "Invoice 1001",
                "processed_at": "2026-05-05T18:00:00",
                "files": [
                    {
                        "attachment_name": "Invoice-1001.pdf",
                        "supplier": "Supplier One",
                        "document_type": "invoice",
                        "amount": "12.00",
                        "needs_review": False,
                        "review_reasons": [],
                        "saved_path": "Documents/Supplier One/Invoices/file.pdf",
                    }
                ],
            },
        )
        record_processed_message(
            "user-1",
            "message-2",
            {
                "status": "processed",
                "sender": "sender@example.com",
                "subject": "Unknown document",
                "processed_at": "2026-05-05T19:00:00",
                "files": [
                    {
                        "attachment_name": "unknown.pdf",
                        "supplier": "Other",
                        "document_type": "unknown",
                        "amount": None,
                        "needs_review": True,
                        "review_reasons": ["unknown_supplier", "unknown_document_type"],
                        "saved_path": "Documents/Needs Review/Other/Other/unknown.pdf",
                    }
                ],
            },
        )
        record_processed_message(
            "user-1",
            "message-3",
            {
                "status": "skipped",
                "sender": "sender@example.com",
                "subject": "Newsletter",
                "processed_at": "2026-05-05T20:00:00",
                "files": [],
            },
        )

        summary = build_tracking_summary("user-1")
        self.assertEqual(summary["tracked_messages"], 3)
        self.assertEqual(summary["processed_messages"], 2)
        self.assertEqual(summary["skipped_messages"], 1)
        self.assertEqual(summary["saved_files"], 2)
        self.assertEqual(summary["needs_review_messages"], 1)
        self.assertEqual(summary["needs_review_files"], 1)
        self.assertEqual(summary["files_by_supplier"]["Supplier One"], 1)
        self.assertEqual(summary["files_by_supplier"]["Other"], 1)
        self.assertEqual(summary["files_by_type"]["invoice"], 1)
        self.assertEqual(summary["files_by_type"]["unknown"], 1)
        self.assertEqual(summary["last_processed_at"], "2026-05-05T20:00:00")

        review_queue = build_review_queue("user-1")
        self.assertEqual(len(review_queue), 1)
        self.assertEqual(review_queue[0]["message_id"], "message-2")
        self.assertEqual(review_queue[0]["review_reasons"], ["unknown_supplier", "unknown_document_type"])


if __name__ == "__main__":
    unittest.main()
