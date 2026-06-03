from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.services.transaction_rules import (
    apply_transaction_rule,
    find_matching_transaction_rule,
    load_transaction_rules,
)
from app.services.vatbook_parser import ParsedVatbookWorkbook, parse_vatbook_workbook


@dataclass(slots=True)
class VatbookImportResult:
    workbook_path: str
    sheet_name: str
    imported_transactions: int
    replaced_transactions: int
    skipped_transactions: int
    annotation_count: int
    first_transaction_date: date | None
    last_transaction_date: date | None
    pubs: list[str]


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_vatbook_path(workbook_path: str | None = None) -> Path:
    root = backend_root()
    if workbook_path is None:
        vatbook_dir = root / "vatbook"
        candidates = sorted(vatbook_dir.glob("*.xlsx"))
        if not candidates:
            raise FileNotFoundError("No VAT workbook was found under backend/vatbook")
        if len(candidates) > 1:
            available = ", ".join(candidate.name for candidate in candidates)
            raise ValueError(
                f"Multiple VAT workbooks were found under backend/vatbook. "
                f"Provide workbook_path explicitly. Available files: {available}"
            )
        return candidates[0]

    candidate = Path(workbook_path)
    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0] == "backend":
            candidate = Path(*candidate.parts[1:])
        candidate = root / candidate

    resolved = candidate.resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        raise ValueError("workbook_path must point to a file inside the backend directory")
    if not resolved.exists():
        raise FileNotFoundError(f"Workbook file was not found: {resolved}")
    if resolved.suffix.lower() != ".xlsx":
        raise ValueError("Workbook file must be an .xlsx file")
    return resolved


async def import_transactions_from_vatbook(
    *,
    db: AsyncSession,
    user_id,
    workbook_path: str | None = None,
    sheet_name: str | None = None,
    replace_existing: bool = True,
) -> VatbookImportResult:
    resolved_path = resolve_vatbook_path(workbook_path)
    workbook = parse_vatbook_workbook(resolved_path, sheet_name=sheet_name)
    source_file = str(resolved_path.relative_to(backend_root()))

    replaced_transactions = 0
    existing_row_numbers: set[int] = set()

    if replace_existing:
        delete_result = await db.execute(
            delete(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.source_type == "vatbook",
                Transaction.source_file == source_file,
                Transaction.source_sheet == workbook.sheet_name,
            )
        )
        replaced_transactions = delete_result.rowcount or 0
    else:
        existing_result = await db.execute(
            select(Transaction.row_number).where(
                Transaction.user_id == user_id,
                Transaction.source_type == "vatbook",
                Transaction.source_file == source_file,
                Transaction.source_sheet == workbook.sheet_name,
            )
        )
        existing_row_numbers = set(existing_result.scalars().all())

    imported_transactions = 0
    skipped_transactions = 0
    annotation_count = 0
    transaction_dates = []
    pubs: set[str] = set()
    rules = await load_transaction_rules(db=db, user_id=user_id, source_type="vatbook")

    for parsed_transaction in workbook.transactions:
        if parsed_transaction.row_number in existing_row_numbers:
            skipped_transactions += 1
            continue

        annotation_count += len(parsed_transaction.annotations)
        if parsed_transaction.transaction_date is not None:
            transaction_dates.append(parsed_transaction.transaction_date)
        if parsed_transaction.pub:
            pubs.add(parsed_transaction.pub)

        transaction = Transaction(
            user_id=user_id,
            source_type="vatbook",
            source_file=source_file,
            source_sheet=workbook.sheet_name,
            row_number=parsed_transaction.row_number,
            posted_account=parsed_transaction.posted_account,
            pub=parsed_transaction.pub,
            transaction_date=parsed_transaction.transaction_date,
            description1=parsed_transaction.description1,
            description2=parsed_transaction.description2,
            debit_amount=parsed_transaction.debit_amount,
            credit_amount=parsed_transaction.credit_amount,
            transaction_type=parsed_transaction.transaction_type,
            category=parsed_transaction.category,
            resale_23_amount=parsed_transaction.resale_23_amount,
            non_resale_23_amount=parsed_transaction.non_resale_23_amount,
            non_resale_13_5_amount=parsed_transaction.non_resale_13_5_amount,
            non_resale_9_amount=parsed_transaction.non_resale_9_amount,
            non_resale_0_amount=parsed_transaction.non_resale_0_amount,
            annotation_types=[annotation.annotation_type for annotation in parsed_transaction.annotations],
            annotation_notes=[annotation.note for annotation in parsed_transaction.annotations],
            has_linked_annotation=any(
                "linked" in annotation.note.lower()
                for annotation in parsed_transaction.annotations
            ),
            raw_row_json={
                "row": parsed_transaction.raw_cells,
                "annotations": [
                    {
                        "row_number": annotation.row_number,
                        "label": annotation.label,
                        "annotation_type": annotation.annotation_type,
                        "note": annotation.note,
                        "raw_cells": annotation.raw_cells,
                    }
                    for annotation in parsed_transaction.annotations
                ],
            },
        )
        matched_rule = find_matching_transaction_rule(transaction=transaction, rules=rules)
        if matched_rule is not None and apply_transaction_rule(transaction=transaction, rule=matched_rule) is not None:
            transaction.reviewed_at = datetime.utcnow()
        db.add(transaction)
        imported_transactions += 1

    await db.flush()

    return VatbookImportResult(
        workbook_path=source_file,
        sheet_name=workbook.sheet_name,
        imported_transactions=imported_transactions,
        replaced_transactions=replaced_transactions,
        skipped_transactions=skipped_transactions,
        annotation_count=annotation_count,
        first_transaction_date=min(transaction_dates) if transaction_dates else None,
        last_transaction_date=max(transaction_dates) if transaction_dates else None,
        pubs=sorted(pubs),
    )
