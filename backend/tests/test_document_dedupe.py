from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pydantic_settings" not in sys.modules:
    fake_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - tiny test shim
        def __init__(self, **_: object) -> None:
            pass

    fake_module.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = fake_module

from app.services.document_dedupe import document_duplicate_fingerprint, pick_canonical_document  # noqa: E402


@dataclass
class _DocumentStub:
    id: str
    created_at: datetime
    drive_file_id: str | None = None
    synced_at: datetime | None = None
    storage_key: str | None = None
    extraction_status: str | None = None
    needs_review: bool = False
    extracted_text: str | None = None
    confidence_score: float | None = None
    attachment_name: str | None = None
    local_path: str | None = None
    supplier: str | None = None
    document_type: str | None = None
    document_date: object | None = None
    reference: str | None = None
    amount: object | None = None


class DocumentDedupeTests(unittest.TestCase):
    def test_prefers_synced_document_as_canonical(self) -> None:
        synced = _DocumentStub(
            id="synced",
            created_at=datetime(2026, 5, 1, 10, 0, 0),
            drive_file_id="drive-file-1",
            synced_at=datetime(2026, 5, 1, 11, 0, 0),
        )
        unsynced = _DocumentStub(
            id="unsynced",
            created_at=datetime(2026, 4, 1, 10, 0, 0),
        )

        canonical, duplicates = pick_canonical_document([unsynced, synced])

        self.assertEqual(canonical.id, "synced")
        self.assertEqual([item.id for item in duplicates], ["unsynced"])

    def test_prefers_oldest_document_when_neither_is_synced(self) -> None:
        older = _DocumentStub(id="older", created_at=datetime(2026, 4, 1, 10, 0, 0))
        newer = _DocumentStub(id="newer", created_at=datetime(2026, 5, 1, 10, 0, 0))

        canonical, duplicates = pick_canonical_document([newer, older])

        self.assertEqual(canonical.id, "older")
        self.assertEqual([item.id for item in duplicates], ["newer"])

    def test_prefers_richer_extracted_document_when_sync_state_is_equal(self) -> None:
        sparse = _DocumentStub(
            id="sparse",
            created_at=datetime(2026, 5, 1, 10, 0, 0),
            extraction_status="pending",
        )
        extracted = _DocumentStub(
            id="extracted",
            created_at=datetime(2026, 5, 2, 10, 0, 0),
            extraction_status="extracted",
            extracted_text="Invoice Total 169.74",
            confidence_score=0.91,
        )

        canonical, duplicates = pick_canonical_document([sparse, extracted])

        self.assertEqual(canonical.id, "extracted")
        self.assertEqual([item.id for item in duplicates], ["sparse"])

    def test_builds_duplicate_fingerprint_from_supplier_statement_metadata(self) -> None:
        document = _DocumentStub(
            id="statement-1",
            created_at=datetime(2026, 4, 30, 12, 0, 0),
            supplier="Connacht Bottlers",
            document_type="statement",
            document_date=datetime(2026, 4, 30).date(),
            amount="1527.48",
            attachment_name="Careys Bar - JJ Mahon - Stmt - 058 - Date - 30-04-2026.pdf",
        )

        fingerprint = document_duplicate_fingerprint(document)

        self.assertIsNotNone(fingerprint)
        self.assertIn("statement|connachtbottlers|2026-04-30", fingerprint)
        self.assertIn("amt:1527.48", fingerprint)


if __name__ == "__main__":
    unittest.main()
