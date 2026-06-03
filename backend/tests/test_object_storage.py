from __future__ import annotations

import shutil
import sys
import types
import unittest
import uuid
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
    from app.models import Document  # noqa: E402
    from app.services import object_storage  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class ObjectStorageTests(unittest.TestCase):
        @unittest.skip(f"object storage tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class _FakeS3Client:
        def __init__(self) -> None:
            self.uploads: list[tuple[str, str, str]] = []
            self.downloads: list[tuple[str, str, str]] = []

        def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs=None) -> None:
            self.uploads.append((filename, bucket, key))

        def download_file(self, bucket: str, key: str, filename: str) -> None:
            self.downloads.append((bucket, key, filename))
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            Path(filename).write_bytes(b"downloaded-pdf")


    class ObjectStorageTests(unittest.TestCase):
        def setUp(self) -> None:
            self.original_backend = object_storage.settings.document_storage_backend
            self.original_bucket = object_storage.settings.s3_bucket
            self.original_prefix = object_storage.settings.s3_prefix
            self.original_client = object_storage._storage_client

            object_storage.settings.document_storage_backend = "s3"
            object_storage.settings.s3_bucket = "test-docs"
            object_storage.settings.s3_prefix = "documents"
            self.fake_client = _FakeS3Client()
            object_storage._storage_client = lambda: self.fake_client

            self.test_dir = Path("Documents/_object_storage_tests")
            self.test_dir.mkdir(parents=True, exist_ok=True)

        def tearDown(self) -> None:
            object_storage.settings.document_storage_backend = self.original_backend
            object_storage.settings.s3_bucket = self.original_bucket
            object_storage.settings.s3_prefix = self.original_prefix
            object_storage._storage_client = self.original_client
            shutil.rmtree(self.test_dir, ignore_errors=True)

        def test_build_object_storage_key_uses_relative_document_path(self) -> None:
            key = object_storage.build_object_storage_key(
                local_path="Documents/Supplier One/Invoices/example.pdf"
            )
            self.assertEqual(key, "documents/Documents/Supplier One/Invoices/example.pdf")

        def test_sync_document_to_object_storage_updates_document_metadata(self) -> None:
            file_path = self.test_dir / "invoice.pdf"
            file_path.write_bytes(b"pdf-data")
            document = Document(
                id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                gmail_message_id="msg-1",
                attachment_name="invoice.pdf",
                supplier="Supplier One",
                document_type="invoice",
                local_path=str(file_path),
            )

            result = object_storage.sync_document_to_object_storage(
                document=document,
                source_path=file_path,
            )

            self.assertEqual(result["status"], "synced")
            self.assertEqual(document.storage_provider, "s3")
            self.assertEqual(document.storage_bucket, "test-docs")
            self.assertTrue(document.storage_key)
            self.assertEqual(len(self.fake_client.uploads), 1)

        def test_ensure_local_document_file_downloads_missing_file_from_storage(self) -> None:
            file_path = self.test_dir / "missing.pdf"
            document = Document(
                id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                gmail_message_id="msg-2",
                attachment_name="missing.pdf",
                supplier="Supplier Two",
                document_type="statement",
                local_path=str(file_path),
                storage_provider="s3",
                storage_bucket="test-docs",
                storage_key="documents/Documents/_object_storage_tests/missing.pdf",
            )

            resolved = object_storage.ensure_local_document_file(document)

            self.assertEqual(resolved, file_path)
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.read_bytes(), b"downloaded-pdf")
            self.assertEqual(
                self.fake_client.downloads,
                [("test-docs", "documents/Documents/_object_storage_tests/missing.pdf", str(file_path))],
            )


if __name__ == "__main__":
    unittest.main()
