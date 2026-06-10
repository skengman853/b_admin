from __future__ import annotations

import sys
import tempfile
import types
import unittest
import uuid
from datetime import date
from decimal import Decimal
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
    from app.models import (  # noqa: E402
        Base,
        Document,
        DocumentExtractionRun,
        DocumentFinancialFact,
        DocumentFinancialRow,
        User,
    )
    from app.services.ai_document_extraction import AIDocumentExtractionResult  # noqa: E402
    from app.services.document_extraction import extract_documents  # noqa: E402
    from app.services.document_financial_backfill import backfill_document_financial_state  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class DocumentExtractionRunTests(unittest.TestCase):
        @unittest.skip(f"document extraction run tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class DocumentExtractionRunTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self) -> None:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
            self.tempdir = tempfile.TemporaryDirectory()
            self.pdf_path = Path(self.tempdir.name) / "sample.pdf"
            self.pdf_path.write_bytes(b"%PDF-1.4 fake")

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.session_factory() as session:
                self.user = User(id=uuid.uuid4(), email="tester@example.com", password_hash="hashed")
                session.add(self.user)
                await session.commit()

        async def asyncTearDown(self) -> None:
            self.tempdir.cleanup()
            await self.engine.dispose()

        async def test_extract_documents_records_invoice_run(self) -> None:
            async with self.session_factory() as session:
                document = Document(
                    id=uuid.uuid4(),
                    user_id=self.user.id,
                    gmail_message_id="invoice-doc",
                    attachment_index=0,
                    derivation_index=0,
                    attachment_name="Bulmers Ireland - Inv 098 - 4100706 - Date 25-03-2026.pdf",
                    supplier="Bulmers",
                    document_type="invoice",
                    local_path=str(self.pdf_path),
                )
                session.add(document)
                await session.commit()

                extracted_text = """INVOICE
Invoice Number
4100706
Invoice Date
25/03/2026
VAT Total
35.73
Total €
876.10
"""
                with (
                    patch("app.services.document_extraction.ensure_local_document_file", return_value=self.pdf_path),
                    patch("app.services.document_extraction.extract_pdf_text", return_value=extracted_text),
                    patch("app.services.document_extraction.should_attempt_ai_extraction", return_value=False),
                    patch("app.services.document_extraction.sync_invoices_from_documents", new=AsyncMock()),
                ):
                    summary = await extract_documents(
                        user=self.user,
                        db=session,
                        limit=1,
                        document_ids=[document.id],
                        force=True,
                    )

                self.assertEqual(summary["extracted"], 1)
                await session.refresh(document)
                self.assertEqual(document.amount, Decimal("876.10"))
                self.assertEqual(document.vat_amount, Decimal("35.73"))

                runs = (
                    await session.execute(
                        select(DocumentExtractionRun).where(DocumentExtractionRun.document_id == document.id)
                    )
                ).scalars().all()
                self.assertEqual(len(runs), 1)
                run = runs[0]
                self.assertEqual(run.extractor_family, "invoice")
                self.assertEqual(run.extractor_profile, "invoice")
                self.assertEqual(run.extractor_version, "document_extraction_v1")
                self.assertEqual(run.source_kind, "rules")
                self.assertEqual(run.status, "extracted")
                self.assertEqual(run.review_reasons, [])
                self.assertEqual(run.raw_payload_json["document_snapshot"]["reference"], "4100706")
                self.assertEqual(run.raw_payload_json["document_snapshot"]["amount"], "876.10")
                self.assertEqual(run.raw_payload_json["document_snapshot"]["vat_amount"], "35.73")

                fact = (
                    await session.execute(
                        select(DocumentFinancialFact).where(DocumentFinancialFact.document_id == document.id)
                    )
                ).scalar_one()
                self.assertEqual(fact.document_type, "invoice")
                self.assertEqual(fact.reference, "4100706")
                self.assertEqual(fact.amount, Decimal("876.10"))
                self.assertEqual(fact.extraction_run_id, run.id)

                rows = (
                    await session.execute(
                        select(DocumentFinancialRow).where(DocumentFinancialRow.extraction_run_id == run.id)
                    )
                ).scalars().all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].row_type, "invoice")
                self.assertEqual(rows[0].reference, "4100706")
                self.assertEqual(rows[0].amount, Decimal("876.10"))

        async def test_extract_documents_records_statement_profile(self) -> None:
            async with self.session_factory() as session:
                document = Document(
                    id=uuid.uuid4(),
                    user_id=self.user.id,
                    gmail_message_id="statement-doc",
                    attachment_index=0,
                    derivation_index=0,
                    attachment_name="Bulmers Ireland - Stmt 018 - Date 30-04-2026.pdf",
                    supplier="Bulmers",
                    document_type="statement",
                    local_path=str(self.pdf_path),
                )
                session.add(document)
                await session.commit()

                extracted_text = """STATEMENT OF ACCOUNT
Customer Account No: 2016632103
Date: 30.04.2026
Please find below your account statement with all items between 01.04.2026 To 30.04.2026:
"""
                with (
                    patch("app.services.document_extraction.ensure_local_document_file", return_value=self.pdf_path),
                    patch("app.services.document_extraction.extract_pdf_text", return_value=extracted_text),
                    patch("app.services.document_extraction.should_attempt_ai_extraction", return_value=False),
                    patch("app.services.document_extraction.sync_invoices_from_documents", new=AsyncMock()),
                ):
                    await extract_documents(
                        user=self.user,
                        db=session,
                        limit=1,
                        document_ids=[document.id],
                        force=True,
                    )

                runs = (
                    await session.execute(
                        select(DocumentExtractionRun).where(DocumentExtractionRun.document_id == document.id)
                    )
                ).scalars().all()
                self.assertEqual(len(runs), 1)
                run = runs[0]
                self.assertEqual(run.extractor_family, "statement")
                self.assertEqual(run.extractor_profile, "statement_of_account")

                fact = (
                    await session.execute(
                        select(DocumentFinancialFact).where(DocumentFinancialFact.document_id == document.id)
                    )
                ).scalar_one()
                self.assertEqual(fact.document_type, "statement")
                self.assertEqual(fact.statement_kind, "supplier_statement")
                self.assertEqual(fact.extraction_run_id, run.id)

                rows = (
                    await session.execute(
                        select(DocumentFinancialRow).where(DocumentFinancialRow.extraction_run_id == run.id)
                    )
                ).scalars().all()
                self.assertEqual(rows, [])

        async def test_extract_documents_uses_ai_primary_for_statement_and_rules_fill_gaps(self) -> None:
            async with self.session_factory() as session:
                document = Document(
                    id=uuid.uuid4(),
                    user_id=self.user.id,
                    gmail_message_id="statement-ai-doc",
                    attachment_index=0,
                    derivation_index=0,
                    attachment_name="JJ Mahon - Stmt 058 - Date - 30-04-2026.pdf",
                    supplier="Connacht Bottlers",
                    document_type="statement",
                    local_path=str(self.pdf_path),
                )
                session.add(document)
                await session.commit()

                extracted_text = """STATEMENT OF ACCOUNT
Date: 30.04.2026
Connacht Bottlers
DD-29-04 Receipt 169.74
"""
                ai_result = AIDocumentExtractionResult(
                    statement_kind="trade_statement",
                    is_financial=True,
                    account_number="CAREY01",
                    period_start="2026-04-01",
                    period_end="2026-04-30",
                    confidence_score=0.91,
                    entries=[
                        {
                            "event_date": "2026-04-29",
                            "reference": "DD-29-04",
                            "transaction_type": "Receipt",
                            "amount": "169.74",
                            "raw_text": "29/04/2026 DD-29-04 Receipt 169.74",
                        }
                    ],
                )
                with (
                    patch("app.services.document_extraction.ensure_local_document_file", return_value=self.pdf_path),
                    patch("app.services.document_extraction.extract_pdf_text", return_value=extracted_text),
                    patch("app.services.document_extraction.should_attempt_ai_extraction", return_value=True),
                    patch("app.services.document_extraction.extract_document_with_ai", new=AsyncMock(return_value=ai_result)),
                    patch("app.services.document_extraction.sync_invoices_from_documents", new=AsyncMock()),
                ):
                    summary = await extract_documents(
                        user=self.user,
                        db=session,
                        limit=1,
                        document_ids=[document.id],
                        force=True,
                    )

                self.assertEqual(summary["extracted"], 1)
                await session.refresh(document)
                self.assertEqual(document.ai_extraction_status, "completed")
                self.assertEqual(document.document_date, date(2026, 4, 30))

                run = (
                    await session.execute(
                        select(DocumentExtractionRun).where(DocumentExtractionRun.document_id == document.id)
                    )
                ).scalar_one()
                self.assertEqual(run.source_kind, "ai_primary")

                fact = (
                    await session.execute(
                        select(DocumentFinancialFact).where(DocumentFinancialFact.document_id == document.id)
                    )
                ).scalar_one()
                self.assertEqual(fact.statement_kind, "trade_statement")
                self.assertEqual(fact.period_start, date(2026, 4, 1))
                self.assertEqual(fact.period_end, date(2026, 4, 30))

                rows = (
                    await session.execute(
                        select(DocumentFinancialRow).where(DocumentFinancialRow.extraction_run_id == run.id)
                    )
                ).scalars().all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].reference, "DD-29-04")
                self.assertEqual(rows[0].amount, Decimal("169.74"))

        async def test_backfill_financial_state_creates_run_fact_and_rows(self) -> None:
            async with self.session_factory() as session:
                document = Document(
                    id=uuid.uuid4(),
                    user_id=self.user.id,
                    gmail_message_id="backfill-doc",
                    attachment_index=0,
                    derivation_index=0,
                    attachment_name="Bulmers Ireland - Inv 098 - 4100706 - Date 25-03-2026.pdf",
                    supplier="Bulmers",
                    document_type="invoice",
                    document_date=date(2026, 3, 25),
                    reference="4100706",
                    amount=Decimal("876.10"),
                    vat_amount=Decimal("35.73"),
                    currency="EUR",
                    extraction_status="extracted",
                    local_path=str(self.pdf_path),
                )
                session.add(document)
                await session.commit()

                summary = await backfill_document_financial_state(
                    user=self.user,
                    db=session,
                    limit=1,
                    document_ids=[document.id],
                    force=True,
                )

                self.assertEqual(summary["backfilled"], 1)

                runs = (
                    await session.execute(
                        select(DocumentExtractionRun).where(DocumentExtractionRun.document_id == document.id)
                    )
                ).scalars().all()
                self.assertEqual(len(runs), 1)
                run = runs[0]
                self.assertTrue(run.raw_payload_json.get("backfill"))

                fact = (
                    await session.execute(
                        select(DocumentFinancialFact).where(DocumentFinancialFact.document_id == document.id)
                    )
                ).scalar_one()
                self.assertEqual(fact.reference, "4100706")
                self.assertEqual(fact.amount, Decimal("876.10"))
                self.assertEqual(fact.extraction_run_id, run.id)

                rows = (
                    await session.execute(
                        select(DocumentFinancialRow).where(DocumentFinancialRow.extraction_run_id == run.id)
                    )
                ).scalars().all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].row_type, "invoice")
                self.assertEqual(rows[0].reference, "4100706")


if __name__ == "__main__":
    unittest.main()
