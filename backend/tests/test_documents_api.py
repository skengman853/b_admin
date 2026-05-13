from __future__ import annotations

import sys
import types
import unittest
import uuid
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
    from fastapi import HTTPException  # noqa: E402
    from sqlalchemy import select  # noqa: E402
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
    from app.api.documents import (  # noqa: E402
        approve_document,
        get_document,
        import_local_documents,
        list_documents,
        list_review_documents,
        split_document,
        update_document,
    )
    from app.models import Base, Document, User  # noqa: E402
    from app.schemas import DocumentUpdateRequest, LocalDocumentImportRequest  # noqa: E402
    from app.services.local_document_import import LocalDocumentImportItem, LocalDocumentImportResult  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class DocumentApiFilterTests(unittest.TestCase):
        @unittest.skip(f"document API tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    MULTI_INVOICE_PACKET_TEXT = """Lovell Bros. Ltd.

INVOICE 881489
01/04/2026
VAT Total
68.66
TOTAL
367.24

INVOICE 881548
01/04/2026
VAT Total
17.84
TOTAL
95.40
"""

    class DocumentApiFilterTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="tester@example.com", password_hash="hashed")
                session.add(self.user)
                session.add_all(
                    [
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="message-review-low",
                            attachment_index=0,
                            attachment_name="review-low.pdf",
                            supplier="Supplier A",
                            document_type="invoice",
                            confidence_score=0.35,
                            extraction_status="review",
                            local_path="Documents/Supplier A/Invoices/review-low.pdf",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="message-review-mid",
                            attachment_index=0,
                            attachment_name="review-mid.pdf",
                            supplier="Supplier B",
                            document_type="invoice",
                            confidence_score=0.60,
                            extraction_status="review",
                            local_path="Documents/Supplier B/Invoices/review-mid.pdf",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="message-extracted-high",
                            attachment_index=0,
                            attachment_name="extracted-high.pdf",
                            supplier="Supplier C",
                            document_type="invoice",
                            confidence_score=0.99,
                            extraction_status="extracted",
                            local_path="Documents/Supplier C/Invoices/extracted-high.pdf",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="message-pending",
                            attachment_index=0,
                            attachment_name="pending.pdf",
                            supplier="Supplier D",
                            document_type="invoice",
                            confidence_score=None,
                            extraction_status="pending",
                            needs_review=True,
                            local_path="Documents/Supplier D/Invoices/pending.pdf",
                        ),
                        Document(
                            user_id=self.user.id,
                            gmail_message_id="message-multi-invoice",
                            attachment_index=0,
                            attachment_name="packet.pdf",
                            supplier="Lovell Bros. Ltd.",
                            document_type="invoice",
                            confidence_score=0.05,
                            extraction_status="review",
                            needs_review=True,
                            review_reasons=["multiple_invoice_records"],
                            local_path="Documents/Lovell Bros. Ltd./Invoices/packet.pdf",
                            extracted_text=MULTI_INVOICE_PACKET_TEXT,
                        ),
                    ]
                )
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_filters_review_documents_by_max_confidence(self) -> None:
            async with self.session_factory() as session:
                payload = await list_documents(
                    extraction_status="review",
                    max_confidence=0.7,
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total, 2)
            self.assertEqual([item.gmail_message_id for item in payload.documents], [
                "message-review-low",
                "message-review-mid",
            ])

        async def test_filters_documents_by_min_confidence(self) -> None:
            async with self.session_factory() as session:
                payload = await list_documents(
                    min_confidence=0.9,
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total, 1)
            self.assertEqual(payload.documents[0].gmail_message_id, "message-extracted-high")

        async def test_rejects_inverted_confidence_range(self) -> None:
            async with self.session_factory() as session:
                with self.assertRaises(HTTPException) as context:
                    await list_documents(
                        min_confidence=0.9,
                        max_confidence=0.5,
                        page=1,
                        limit=50,
                        user=self.user,
                        db=session,
                    )

            self.assertEqual(context.exception.status_code, 422)

        async def test_lists_combined_review_queue(self) -> None:
            async with self.session_factory() as session:
                payload = await list_review_documents(
                    confidence_below=0.7,
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total, 3)
            self.assertEqual([item.gmail_message_id for item in payload.documents], [
                "message-pending",
                "message-review-low",
                "message-review-mid",
            ])

        async def test_manual_update_can_resolve_review_item(self) -> None:
            async with self.session_factory() as session:
                review_payload = await list_review_documents(
                    confidence_below=0.7,
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )
                target = review_payload.documents[0]

                with patch(
                    "app.api.documents.refile_document_assets",
                    new=AsyncMock(return_value={"local_moved": True, "drive_updated": False}),
                ):
                    updated = await update_document(
                        document_id=str(target.id),
                        body=DocumentUpdateRequest(
                            supplier="Resolved Supplier",
                            reference="MANUAL-001",
                            mark_reviewed=True,
                        ),
                        user=self.user,
                        db=session,
                    )

                    refreshed_review_payload = await list_review_documents(
                        confidence_below=0.7,
                        page=1,
                        limit=50,
                        user=self.user,
                        db=session,
                    )

            self.assertEqual(updated.supplier, "Resolved Supplier")
            self.assertEqual(updated.reference, "MANUAL-001")
            self.assertFalse(updated.needs_review)
            self.assertEqual(updated.review_reasons, [])
            self.assertEqual(updated.extraction_status, "reviewed")
            self.assertNotIn(target.id, [item.id for item in refreshed_review_payload.documents])

        async def test_approve_document_resolves_without_metadata_changes(self) -> None:
            async with self.session_factory() as session:
                review_payload = await list_review_documents(
                    confidence_below=0.7,
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )
                target = review_payload.documents[1]

                with patch(
                    "app.api.documents.refile_document_assets",
                    new=AsyncMock(return_value={"local_moved": False, "drive_updated": False}),
                ):
                    approved = await approve_document(
                        document_id=target.id,
                        user=self.user,
                        db=session,
                    )

                    refreshed_review_payload = await list_review_documents(
                        confidence_below=0.7,
                        page=1,
                        limit=50,
                        user=self.user,
                        db=session,
                    )

            self.assertFalse(approved.needs_review)
            self.assertEqual(approved.review_reasons, [])
            self.assertEqual(approved.extraction_status, "reviewed")

        async def test_import_local_documents_validates_service_dataclasses(self) -> None:
            local_document_id = uuid.uuid4()
            with patch(
                "app.api.documents.import_documents_from_local_archive",
                new=AsyncMock(
                    return_value=LocalDocumentImportResult(
                        source_path="import_sources/Invoices - Pubs",
                        scanned_files=3,
                        eligible_files=2,
                        imported_documents=1,
                        extracted_documents=1,
                        skipped_files=2,
                        results=[
                            LocalDocumentImportItem(
                                relative_path="Diageo/Careys Bar/Invoices/diageo.pdf",
                                supplier="Diageo",
                                document_type="invoice",
                                pub_hint="Careys Bar",
                                status="imported",
                                reason=None,
                                saved_path="Documents/Diageo/Invoices/diageo.pdf",
                                document_id=str(local_document_id),
                            )
                        ],
                    )
                ),
            ):
                async with self.session_factory() as session:
                    payload = await import_local_documents(
                        body=LocalDocumentImportRequest(
                            source_path="backend/import_sources/Invoices - Pubs",
                        ),
                        user=self.user,
                        db=session,
                    )

            self.assertEqual(payload.imported_documents, 1)
            self.assertEqual(payload.results[0].supplier, "Diageo")
            self.assertEqual(payload.results[0].document_id, local_document_id)
            self.assertNotIn(target.id, [item.id for item in refreshed_review_payload.documents])

        async def test_split_document_creates_child_records_and_resolves_parent_review(self) -> None:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(Document).where(Document.gmail_message_id == "message-multi-invoice")
                )
                target = result.scalar_one()

                split_payload = await split_document(
                    document_id=target.id,
                    user=self.user,
                    db=session,
                )

                refreshed_parent = await session.get(Document, target.id)
                child_result = await session.execute(
                    select(Document)
                    .where(Document.parent_document_id == target.id)
                    .order_by(Document.derivation_index.asc())
                )
                children = list(child_result.scalars().all())

            self.assertEqual(split_payload.created, 2)
            self.assertEqual(split_payload.updated, 0)
            self.assertEqual(split_payload.deleted, 0)
            self.assertEqual(split_payload.parent_document.extraction_status, "split")
            self.assertFalse(split_payload.parent_document.needs_review)
            self.assertEqual(len(split_payload.child_documents), 2)
            self.assertEqual([child.reference for child in split_payload.child_documents], ["881489", "881548"])
            self.assertEqual([str(child.amount) for child in split_payload.child_documents], ["367.24", "95.40"])
            self.assertIsNotNone(refreshed_parent)
            self.assertEqual(refreshed_parent.extraction_status, "split")
            self.assertFalse(refreshed_parent.needs_review)
            self.assertEqual(len(children), 2)
            self.assertTrue(all(child.parent_document_id == target.id for child in children))
            self.assertEqual([child.derivation_index for child in children], [1, 2])

        async def test_list_documents_hides_split_parents_by_default(self) -> None:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(Document).where(Document.gmail_message_id == "message-multi-invoice")
                )
                target = result.scalar_one()
                await split_document(
                    document_id=target.id,
                    user=self.user,
                    db=session,
                )

                payload = await list_documents(
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )
                payload_with_containers = await list_documents(
                    include_split_containers=True,
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            default_ids = [item.gmail_message_id for item in payload.documents]
            self.assertEqual(default_ids.count("message-multi-invoice"), 2)
            self.assertEqual(payload.total, 6)
            self.assertEqual(payload_with_containers.total, 7)
            split_parents = [item for item in payload_with_containers.documents if item.extraction_status == "split"]
            self.assertEqual(len(split_parents), 1)

        async def test_get_document_returns_split_relationship_context(self) -> None:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(Document).where(Document.gmail_message_id == "message-multi-invoice")
                )
                target = result.scalar_one()
                await split_document(
                    document_id=target.id,
                    user=self.user,
                    db=session,
                )

                parent_detail = await get_document(
                    document_id=target.id,
                    user=self.user,
                    db=session,
                )
                child_id = parent_detail.child_documents[0].id
                child_detail = await get_document(
                    document_id=child_id,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(parent_detail.extraction_status, "split")
            self.assertIsNone(parent_detail.parent_document)
            self.assertEqual([child.reference for child in parent_detail.child_documents], ["881489", "881548"])
            self.assertIsNotNone(child_detail.parent_document)
            self.assertEqual(child_detail.parent_document.id, target.id)
            self.assertEqual(child_detail.parent_document.extraction_status, "split")
            self.assertEqual(child_detail.child_documents, [])

        async def test_list_documents_orders_packet_children_in_invoice_order(self) -> None:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(Document).where(Document.gmail_message_id == "message-multi-invoice")
                )
                target = result.scalar_one()
                await split_document(
                    document_id=target.id,
                    user=self.user,
                    db=session,
                )

                payload = await list_documents(
                    parent_document_id=target.id,
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total, 2)
            self.assertEqual([item.reference for item in payload.documents], ["881489", "881548"])
            self.assertEqual([item.derivation_index for item in payload.documents], [1, 2])


if __name__ == "__main__":
    unittest.main()
