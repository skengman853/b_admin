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
from app.services.local_storage import copy_to_final_storage, move_to_final_storage, relocate_existing_file


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

    def test_relocates_existing_file_to_resolved_destination(self) -> None:
        documents_root = Path(settings.documents_root)
        source_dir = documents_root / "Needs Review" / "Other" / "Invoices"
        source_dir.mkdir(parents=True, exist_ok=True)
        source_file = source_dir / "unknown_date_other_invoice_pfinv_121_490_00.pdf"
        source_file.write_bytes(b"resolved-review-file")

        destination = relocate_existing_file(
            current_path=str(source_file),
            supplier="Chris Lynch Skip Hire & Waste Management Services",
            document_type="invoice",
            final_name="2026-05-06_chris_lynch_skip_hire_waste_management_services_invoice_pfinv_121_490_00.pdf",
            needs_review=False,
        )

        self.assertFalse(source_file.exists())
        self.assertTrue(destination.exists())
        self.assertNotIn("Needs Review", destination.parts)
        self.assertEqual(
            destination.parent,
            documents_root / "Chris Lynch Skip Hire & Waste Management Services" / "Invoices",
        )

    def test_copies_existing_file_without_mutating_source(self) -> None:
        source_dir = Path(self._tmpdir.name) / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        source_file = source_dir / "invoice.pdf"
        source_file.write_bytes(b"copy-me")

        destination = copy_to_final_storage(
            source_path=source_file,
            supplier="Supplier Name",
            document_type="invoice",
            final_name="invoice.pdf",
        )

        self.assertTrue(source_file.exists())
        self.assertTrue(destination.exists())
        self.assertEqual(destination.read_bytes(), b"copy-me")


if __name__ == "__main__":
    unittest.main()
