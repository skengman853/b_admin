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
from app.services.local_storage import move_to_final_storage


class MoveToFinalStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_documents_root = settings.documents_root
        self._original_temp_pdfs_root = settings.temp_pdfs_root
        settings.documents_root = str(Path(self._tmpdir.name) / "Documents")
        settings.temp_pdfs_root = str(Path(self._tmpdir.name) / "temp_pdfs")

    def tearDown(self) -> None:
        settings.documents_root = self._original_documents_root
        settings.temp_pdfs_root = self._original_temp_pdfs_root
        self._tmpdir.cleanup()

    def test_reuses_existing_path_for_identical_file(self) -> None:
        temp_dir = Path(settings.temp_pdfs_root)
        temp_dir.mkdir(parents=True, exist_ok=True)

        first_temp = temp_dir / "message-one.pdf"
        second_temp = temp_dir / "message-two.pdf"
        first_temp.write_bytes(b"same-pdf-content")
        second_temp.write_bytes(b"same-pdf-content")

        first_destination = move_to_final_storage(
            temp_path=first_temp,
            supplier="Supplier Name",
            document_type="invoice",
            final_name="2026-05-05_supplier_name_invoice_inv_100_10_00.pdf",
        )
        second_destination = move_to_final_storage(
            temp_path=second_temp,
            supplier="Supplier Name",
            document_type="invoice",
            final_name="2026-05-05_supplier_name_invoice_inv_100_10_00.pdf",
        )

        self.assertEqual(first_destination, second_destination)
        self.assertTrue(first_destination.exists())
        self.assertFalse(second_temp.exists())
        self.assertEqual(len(list(first_destination.parent.glob("*.pdf"))), 1)

    def test_routes_uncertain_files_to_needs_review(self) -> None:
        temp_dir = Path(settings.temp_pdfs_root)
        temp_dir.mkdir(parents=True, exist_ok=True)

        temp_file = temp_dir / "unknown.pdf"
        temp_file.write_bytes(b"review-me")

        destination = move_to_final_storage(
            temp_path=temp_file,
            supplier="Other",
            document_type="unknown",
            final_name="unknown_date_other_unknown_unknown_ref_unknown_amount.pdf",
            needs_review=True,
        )

        self.assertIn("Needs Review", destination.parts)
        self.assertTrue(destination.exists())
        self.assertEqual(destination.parent.name, "Other")


if __name__ == "__main__":
    unittest.main()
