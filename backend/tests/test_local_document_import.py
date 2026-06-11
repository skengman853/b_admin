from __future__ import annotations

import sys
import tempfile
import types
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch


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
    import aiosqlite  # noqa: F401,E402
    from sqlalchemy import select  # noqa: E402
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

    from app.config import settings  # noqa: E402
    from app.models import Base, Document, Transaction, User  # noqa: E402
    from app.services.local_document_import import (  # noqa: E402
        import_documents_from_local_archive,
        import_statement_context_from_local_archive,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class LocalDocumentImportTests(unittest.TestCase):
        @unittest.skip(f"local document import tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class LocalDocumentImportTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="archive@example.com", password_hash="hashed")
                session.add(self.user)
                await session.commit()

            self._tmpdir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
            self.tmp_path = Path(self._tmpdir.name)
            self._original_documents_root = settings.documents_root
            self._original_temp_pdfs_root = settings.temp_pdfs_root
            settings.documents_root = str(self.tmp_path / "Documents")
            settings.temp_pdfs_root = str(self.tmp_path / "temp_pdfs")

        async def asyncTearDown(self) -> None:
            settings.documents_root = self._original_documents_root
            settings.temp_pdfs_root = self._original_temp_pdfs_root
            self._tmpdir.cleanup()
            await self.engine.dispose()

        async def test_imports_filtered_archive_documents(self) -> None:
            archive_root = self.tmp_path / "import_sources" / "Invoices - Pubs"
            diageo_invoice = archive_root / "Diageo" / "Careys Bar" / "Invoices" / (
                "Diageo Inv - 263 - Invoice Number - 9263312263 - Date - 02-04-2026.pdf"
            )
            diageo_linked_invoice = archive_root / "Diageo" / "Careys Bar" / "Invoices" / (
                "Diageo Inv - 263 - Invoice Number - 9263312263 - Date - 02-04-2026 - Linked.pdf"
            )
            moodmaster_invoice = archive_root / "MoodMaster" / "Invoices" / "Careys Bar" / (
                "MoodMaster 066 - Invoice - 111769 - Date - 03-04-2026.pdf"
            )
            archived_invoice = archive_root / "Diageo" / "Careys Bar" / "Invoices" / "Archive" / (
                "Diageo Inv - old - Invoice Number - 9263200000 - Date - 15-11-2025.pdf"
            )
            documentation_file = archive_root / "Zurich" / "Documentation" / "notes.pdf"

            for path in [diageo_invoice, diageo_linked_invoice, moodmaster_invoice, archived_invoice, documentation_file]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"%PDF-1.4\narchive-test")

            async with self.session_factory() as session:
                result = await import_documents_from_local_archive(
                    user=self.user,
                    db=session,
                    source_path=str(archive_root),
                    limit=10,
                    supplier_filters=["diageo", "moodmaster"],
                    pub_filters=["careys"],
                    month="2026-04",
                    extract_after_import=False,
                )

                documents = list(
                    (
                        await session.execute(
                            select(Document).where(Document.user_id == self.user.id).order_by(Document.supplier.asc())
                        )
                    ).scalars().all()
                )

            self.assertEqual(result.imported_documents, 2)
            self.assertEqual(result.extracted_documents, 0)
            self.assertEqual(len(documents), 2)
            self.assertEqual([document.supplier for document in documents], ["Automatic Amusements", "Diageo"])
            self.assertEqual({document.document_type for document in documents}, {"invoice"})
            self.assertTrue(all(Path(document.local_path).exists() for document in documents))
            self.assertEqual(
                len({document.local_path for document in documents}),
                2,
            )
            self.assertIn("archive_directory", {item.reason for item in result.results if item.status == "skipped"})
            self.assertIn("unknown_document_type", {item.reason for item in result.results if item.status == "skipped"})

        async def test_pub_folder_is_not_attributed_as_supplier(self) -> None:
            archive_root = self.tmp_path / "import_sources" / "Statements - Pubs"
            statement_path = archive_root / "Canal Turn" / "Sub Account Statements" / (
                "Sub Account Statements TCT003 - Date 05.07.2021.pdf"
            )
            statement_path.parent.mkdir(parents=True, exist_ok=True)
            statement_path.write_bytes(b"%PDF-1.4\narchive-test")

            async with self.session_factory() as session:
                result = await import_documents_from_local_archive(
                    user=self.user,
                    db=session,
                    source_path=str(archive_root),
                    limit=10,
                    extract_after_import=False,
                )

                documents = list(
                    (
                        await session.execute(
                            select(Document).where(Document.user_id == self.user.id)
                        )
                    ).scalars().all()
                )

            self.assertEqual(result.imported_documents, 1)
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0].supplier, "Other")
            self.assertIn("unknown_supplier", documents[0].review_reasons)
            imported_item = next(item for item in result.results if item.status == "imported")
            self.assertEqual(imported_item.pub_hint, "Canal Turn")

        async def test_extracts_after_import_when_requested(self) -> None:
            archive_root = self.tmp_path / "import_sources" / "Invoices - Pubs"
            invoice_path = archive_root / "David Campbell t-a Little Luxuries" / "Invoices" / (
                "David Campbell t-a Little Luxuries 017 - Inv No 259 - Date 09-04-2026.pdf"
            )
            invoice_path.parent.mkdir(parents=True, exist_ok=True)
            invoice_path.write_bytes(b"%PDF-1.4\narchive-test")

            with patch(
                "app.services.local_document_import.extract_documents",
                new=AsyncMock(return_value={"requested": 1, "extracted": 1, "skipped": 0, "results": []}),
            ) as extract_mock:
                async with self.session_factory() as session:
                    result = await import_documents_from_local_archive(
                        user=self.user,
                        db=session,
                        source_path=str(archive_root),
                        limit=10,
                        month="2026-04",
                        extract_after_import=True,
                    )

            self.assertEqual(result.imported_documents, 1)
            self.assertEqual(result.extracted_documents, 1)
            self.assertEqual(extract_mock.await_count, 1)
            self.assertEqual(len(extract_mock.await_args.kwargs["document_ids"]), 1)

        async def test_imports_adjacent_month_statement_context_for_statement_suppliers(self) -> None:
            archive_root = self.tmp_path / "import_sources" / "Invoices - Pubs"
            careys_april_statement = archive_root / "Heineken" / "Statement Summaries - New" / "Careys Bar" / (
                "Heineken - 050 - Statement Summary - Date - 02-04-2026.pdf"
            )
            careys_may_statement = archive_root / "Heineken" / "Statement Summaries - New" / "Careys Bar" / (
                "Heineken - 051 - Statement Summary - Date - 05-05-2026.pdf"
            )
            canal_may_statement = archive_root / "Heineken" / "Statement Summaries - New" / "Canal Turn" / (
                "Heineken - TCT051 - Statement Summary - Date - 05-05-2026.pdf"
            )
            june_statement = archive_root / "Heineken" / "Statement Summaries - New" / "Careys Bar" / (
                "Heineken - 052 - Statement Summary - Date - 03-06-2026.pdf"
            )
            invoice_path = archive_root / "Heineken" / "Invoices" / "Careys Bar" / (
                "Heineken - 194141091 - Date - 01-04-2026.pdf"
            )
            for path in [careys_april_statement, careys_may_statement, canal_may_statement, june_statement, invoice_path]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"%PDF-1.4\nstatement-context-test")

            async with self.session_factory() as session:
                session.add(
                    Transaction(
                        user_id=self.user.id,
                        source_type="bank_statement",
                        source_file="bank.pdf",
                        source_sheet="careys",
                        row_number=1,
                        pub="Careys",
                        transaction_date=date(2026, 4, 7),
                        description1="D/D HEINEKEN IRELA",
                        raw_row_json={},
                    )
                )
                await session.commit()

                result = await import_statement_context_from_local_archive(
                    user=self.user,
                    db=session,
                    source_path=str(archive_root),
                    month="2026-04",
                    source_type="bank_statement",
                    pub="Careys",
                    adjacent_months=1,
                    extract_after_import=False,
                )

                documents = list(
                    (
                        await session.execute(
                            select(Document).where(Document.user_id == self.user.id).order_by(Document.document_date.asc())
                        )
                    ).scalars().all()
                )

            self.assertEqual(result.suppliers_considered, ["Heineken"])
            self.assertEqual(result.months_considered, ["2026-03", "2026-04", "2026-05"])
            self.assertEqual(result.pubs_considered, ["Careys"])
            self.assertEqual(result.imported_documents, 2)
            self.assertEqual(len(documents), 2)
            self.assertTrue(all(document.document_type == "statement" for document in documents))
            self.assertTrue(all(document.pub in (None, "") or document.pub == "Careys Bar" for document in documents))
            imported_paths = {Path(document.local_path).name for document in documents}
            self.assertIn("Careys Bar - Heineken - 050 - Statement Summary - Date - 02-04-2026.pdf", imported_paths)
            self.assertIn("Careys Bar - Heineken - 051 - Statement Summary - Date - 05-05-2026.pdf", imported_paths)


if __name__ == "__main__":
    unittest.main()
