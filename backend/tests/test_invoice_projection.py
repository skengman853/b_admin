from __future__ import annotations

import sys
import types
import unittest
import uuid
from datetime import date
from decimal import Decimal
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
    import aiosqlite  # noqa: F401,E402
    from sqlalchemy import select  # noqa: E402
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
    from app.api.dashboard import get_summary  # noqa: E402
    from app.api.documents import split_document  # noqa: E402
    from app.api.invoices import list_invoices, update_invoice  # noqa: E402
    from app.models import Base, Document, User  # noqa: E402
    from app.schemas import InvoiceUpdateRequest  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class InvoiceProjectionTests(unittest.TestCase):
        @unittest.skip(f"invoice projection tests require app dependencies: {_missing_dependencies}")
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

    class InvoiceProjectionTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="tester@example.com", password_hash="hashed")
                session.add(self.user)
                self.single_invoice_document = Document(
                    user_id=self.user.id,
                    gmail_message_id="message-single-invoice",
                    attachment_index=0,
                    attachment_name="single.pdf",
                    supplier="Supplier One",
                    document_type="invoice",
                    document_date=date(2026, 4, 5),
                    reference="INV-1001",
                    amount=Decimal("120.00"),
                    vat_amount=Decimal("20.00"),
                    currency="EUR",
                    confidence_score=0.98,
                    extraction_status="extracted",
                    local_path="Documents/Supplier One/Invoices/single.pdf",
                    needs_review=False,
                    review_reasons=[],
                    source_email_subject="Invoice INV-1001",
                )
                self.packet_parent_document = Document(
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
                    source_email_subject="Statement Attached",
                )
                session.add_all([self.single_invoice_document, self.packet_parent_document])
                await session.commit()

        async def asyncTearDown(self) -> None:
            await self.engine.dispose()

        async def test_list_invoices_excludes_multi_invoice_parents_until_split(self) -> None:
            async with self.session_factory() as session:
                payload = await list_invoices(
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )

            self.assertEqual(payload.total, 1)
            self.assertEqual(payload.invoices[0].document_id, self.single_invoice_document.id)
            self.assertEqual(payload.invoices[0].reference, "INV-1001")
            self.assertEqual(str(payload.invoices[0].amount), "120.00")
            self.assertEqual(payload.invoices[0].status, "ready")

        async def test_split_projects_children_into_invoice_rows_and_updates_dashboard(self) -> None:
            async with self.session_factory() as session:
                await session.delete(await session.get(Document, self.single_invoice_document.id))
                await session.commit()

                await split_document(
                    document_id=self.packet_parent_document.id,
                    user=self.user,
                    db=session,
                )
                invoices = await list_invoices(
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )
                summary = await get_summary(
                    month="2026-04",
                    user=self.user,
                    db=session,
                )

            self.assertEqual(invoices.total, 2)
            self.assertEqual([invoice.reference for invoice in invoices.invoices], ["881489", "881548"])
            self.assertEqual([str(invoice.amount) for invoice in invoices.invoices], ["367.24", "95.40"])
            self.assertEqual(str(summary.total_spend), "462.64")
            self.assertEqual(summary.invoice_count, 2)
            self.assertEqual(summary.pending_review, 0)

        async def test_update_invoice_updates_linked_document_fields(self) -> None:
            async with self.session_factory() as session:
                invoices = await list_invoices(
                    page=1,
                    limit=50,
                    user=self.user,
                    db=session,
                )
                invoice = invoices.invoices[0]
                updated = await update_invoice(
                    invoice_id=invoice.id,
                    body=InvoiceUpdateRequest(
                        supplier_name="Updated Supplier",
                        reference="INV-1001-REV",
                        amount=Decimal("130.00"),
                        vat_amount=Decimal("21.00"),
                        invoice_date=date(2026, 4, 6),
                        status="paid",
                    ),
                    user=self.user,
                    db=session,
                )
                refreshed_document = await session.get(Document, self.single_invoice_document.id)

            self.assertEqual(updated.supplier_name, "Updated Supplier")
            self.assertEqual(updated.reference, "INV-1001-REV")
            self.assertEqual(str(updated.amount), "130.00")
            self.assertEqual(str(updated.vat_amount), "21.00")
            self.assertEqual(updated.invoice_date, date(2026, 4, 6))
            self.assertEqual(updated.status, "paid")
            self.assertIsNotNone(refreshed_document)
            self.assertEqual(refreshed_document.supplier, "Updated Supplier")
            self.assertEqual(refreshed_document.reference, "INV-1001-REV")
            self.assertEqual(str(refreshed_document.amount), "130.00")
            self.assertEqual(str(refreshed_document.vat_amount), "21.00")
            self.assertEqual(refreshed_document.document_date, date(2026, 4, 6))


if __name__ == "__main__":
    unittest.main()
