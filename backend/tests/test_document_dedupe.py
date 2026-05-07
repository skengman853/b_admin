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

from app.services.document_dedupe import pick_canonical_document  # noqa: E402


@dataclass
class _DocumentStub:
    id: str
    created_at: datetime
    drive_file_id: str | None = None
    synced_at: datetime | None = None


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


if __name__ == "__main__":
    unittest.main()
