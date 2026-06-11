from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentExtractionRun, DocumentFinancialFact, DocumentFinancialRow
from app.services.document_ledger import ParsedDocumentLedger, ParsedLedgerEntry, build_document_ledger
from app.services.statement_arithmetic import ArithmeticRow, verify_statement_arithmetic
from app.services.supplier_profiles import canonicalize_supplier_name


async def sync_document_financial_state(
    *,
    db: AsyncSession,
    document: Document,
    extraction_run: DocumentExtractionRun,
) -> None:
    # Writer path: parsing here is what creates the persisted rows.
    ledger = build_document_ledger(document, allow_parse_fallback=True)

    fact = (
        await db.execute(
            select(DocumentFinancialFact).where(DocumentFinancialFact.document_id == document.id)
        )
    ).scalar_one_or_none()
    if fact is None:
        fact = DocumentFinancialFact(
            user_id=document.user_id,
            document_id=document.id,
        )

    fact.extraction_run_id = extraction_run.id
    fact.supplier_canonical = canonicalize_supplier_name(document.supplier) or document.supplier or "Other"
    fact.pub_hint = _document_pub_hint(document)
    fact.document_type = document.document_type
    fact.statement_kind = _statement_kind(document=document, ledger=ledger)
    fact.reference = document.reference
    fact.document_date = document.document_date
    fact.period_start = ledger.period_start if ledger is not None else None
    fact.period_end = ledger.period_end if ledger is not None else None
    fact.amount = document.amount
    fact.vat_amount = document.vat_amount
    fact.currency = document.currency
    fact.account_number = _account_number(document=document, ledger=ledger)
    fact.account_name = _account_name(document=document, ledger=ledger)
    fact.opening_balance = _control_total(document=document, ledger=ledger, field="opening_balance")
    fact.closing_balance = _control_total(document=document, ledger=ledger, field="closing_balance")
    fact.total_due = _control_total(document=document, ledger=ledger, field="total_due")
    fact.settlement_discount_total = _control_total(
        document=document, ledger=ledger, field="settlement_discount_total"
    )
    fact.is_financial = _is_financial(document=document, ledger=ledger)
    fact.is_primary_version = True
    _apply_statement_arithmetic(document=document, ledger=ledger, fact=fact)
    db.add(fact)

    # Rows reflect the latest extraction only; older runs keep their history in raw_payload_json.
    await db.execute(
        delete(DocumentFinancialRow).where(DocumentFinancialRow.document_id == document.id)
    )
    if ledger is None:
        return

    for row_index, entry in enumerate(ledger.entries):
        db.add(
            DocumentFinancialRow(
                user_id=document.user_id,
                document_id=document.id,
                extraction_run_id=extraction_run.id,
                row_index=row_index,
                row_type=entry.entry_kind,
                reference=entry.reference,
                clearing_reference=entry.related_reference,
                event_date=entry.event_date,
                due_date=entry.due_date,
                amount=entry.amount,
                signed_amount=entry.signed_amount,
                currency=entry.currency,
                description=_row_description(entry),
                raw_text=entry.raw_text,
                confidence_score=document.confidence_score,
                is_financial=entry.is_financial,
            )
        )


def _statement_kind(*, document: Document, ledger: ParsedDocumentLedger | None) -> str | None:
    if ledger is not None and ledger.statement_kind:
        return ledger.statement_kind
    payload = document.ai_extraction_payload or {}
    value = payload.get("statement_kind")
    return value if isinstance(value, str) and value.strip() else None


def _account_number(*, document: Document, ledger: ParsedDocumentLedger | None) -> str | None:
    if ledger is not None and ledger.account_number:
        return ledger.account_number
    payload = document.ai_extraction_payload or {}
    value = payload.get("account_number")
    return value if isinstance(value, str) and value.strip() else None


def _account_name(*, document: Document, ledger: ParsedDocumentLedger | None) -> str | None:
    if ledger is not None and ledger.account_name:
        return ledger.account_name
    payload = document.ai_extraction_payload or {}
    value = payload.get("account_name")
    return value if isinstance(value, str) and value.strip() else None


def _control_total(*, document: Document, ledger: ParsedDocumentLedger | None, field: str) -> Decimal | None:
    if ledger is not None:
        value = getattr(ledger, field)
        if value is not None:
            return value
    payload = document.ai_extraction_payload or {}
    return _payload_decimal(payload.get(field))


def _payload_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _apply_statement_arithmetic(
    *,
    document: Document,
    ledger: ParsedDocumentLedger | None,
    fact: DocumentFinancialFact,
) -> None:
    if document.document_type != "statement":
        fact.arithmetic_mode = None
        fact.arithmetic_status = None
        fact.arithmetic_delta = None
        return

    rows = [
        ArithmeticRow(kind=entry.entry_kind, amount=entry.amount, event_date=entry.event_date)
        for entry in (ledger.entries if ledger is not None else [])
    ]
    result = verify_statement_arithmetic(
        rows=rows,
        opening_balance=fact.opening_balance,
        closing_balance=fact.closing_balance,
        total_due=fact.total_due,
        settlement_discount_total=fact.settlement_discount_total,
        statement_kind=fact.statement_kind,
        period_start=fact.period_start,
    )
    fact.arithmetic_mode = result.mode
    fact.arithmetic_status = result.status
    fact.arithmetic_delta = result.delta


def _is_financial(*, document: Document, ledger: ParsedDocumentLedger | None) -> bool:
    if ledger is not None:
        return ledger.is_financial
    payload = document.ai_extraction_payload or {}
    ai_value = payload.get("is_financial")
    if isinstance(ai_value, bool):
        return ai_value
    return document.document_type in {"invoice", "credit_note", "receipt", "statement"}


def _row_description(entry: ParsedLedgerEntry) -> str | None:
    if entry.raw_text:
        return entry.raw_text
    parts = [entry.reference, entry.related_reference]
    joined = " / ".join(part for part in parts if part)
    return joined or None


def _document_pub_hint(document: Document) -> str | None:
    haystacks = [
        document.local_path or "",
        document.drive_folder_path or "",
        document.attachment_name or "",
        document.source_email_subject or "",
        document.extracted_text or "",
    ]
    lowered = " ".join(haystacks).lower()
    if any(token in lowered for token in ("careys", "careys pub", "careys tavern", "car18", "carey01", "mardyke")):
        return "Careys"
    if any(token in lowered for token in ("canal", "canal turn", "can02", "cana01", "ballymahon")):
        return "Canal"
    if "corrcross" in lowered:
        return "Corrcross"
    return None
