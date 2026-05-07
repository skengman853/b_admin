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

from app.config import settings  # noqa: E402
from app.services.drive_paths import drive_path_parts_for_local_path  # noqa: E402


class DrivePathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_documents_root = settings.documents_root
        self._original_drive_root = settings.drive_documents_root
        settings.documents_root = "Documents"
        settings.drive_documents_root = "Pub Docs"

    def tearDown(self) -> None:
        settings.documents_root = self._original_documents_root
        settings.drive_documents_root = self._original_drive_root
        self._tmpdir.cleanup()

    def test_drive_path_parts_follow_local_document_structure(self) -> None:
        parts = drive_path_parts_for_local_path("Documents/Supplier One/Invoices/example.pdf")
        self.assertEqual(parts, ["Pub Docs", "Supplier One", "Invoices"])

    def test_drive_path_parts_prefix_relative_paths_without_documents_root(self) -> None:
        parts = drive_path_parts_for_local_path("Needs Review/Other/Invoices/example.pdf")
        self.assertEqual(parts, ["Pub Docs", "Needs Review", "Other", "Invoices"])


if __name__ == "__main__":
    unittest.main()
