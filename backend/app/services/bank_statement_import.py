from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.services.bank_statement_parser import (
    ParsedBankStatement,
    parse_aib_bank_statement_pdf,
)
from app.services.transaction_rules import (
    apply_transaction_rule,
    find_matching_transaction_rule,
    load_transaction_rules,
)
from app.services.vatbook_import import backend_root


@dataclass(slots=True)
class BankStatementImportResult:
    statement_path: str
    account_name: str | None
    account_number: str | None
    provider: str
    imported_transactions: int
    replaced_transactions: int
    skipped_transactions: int
    annotation_count: int
    first_transaction_date: date | None
    last_transaction_date: date | None
    pubs: list[str]


def resolve_bank_statement_path(statement_path: str | None = None) -> Path:
    root = backend_root()
    if statement_path is None:
        bank_statement_dir = root / "bankstatements"
        candidates = sorted(bank_statement_dir.glob("*.pdf"))
        if not candidates:
            raise FileNotFoundError("No bank statement PDF was found under backend/bankstatements")
        if len(candidates) > 1:
            available = ", ".join(candidate.name for candidate in candidates)
            raise ValueError(
                "Multiple bank statement PDFs were found under backend/bankstatements. "
                f"Provide statement_path explicitly. Available files: {available}"
            )
        return candidates[0]

    candidate = Path(statement_path)
    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0] == "backend":
            candidate = Path(*candidate.parts[1:])
        candidate = root / candidate

    resolved = candidate.resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        raise ValueError("statement_path must point to a file inside the backend directory")
    if not resolved.exists():
        raise FileNotFoundError(f"Bank statement file was not found: {resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise ValueError("Bank statement file must be a .pdf file")
    return resolved


async def import_transactions_from_bank_statement(
    *,
    db: AsyncSession,
    user_id,
    statement_path: str | None = None,
    replace_existing: bool = True,
) -> BankStatementImportResult:
    resolved_path = resolve_bank_statement_path(statement_path)
    parsed_statement = parse_aib_bank_statement_pdf(resolved_path)
    source_file = str(resolved_path.relative_to(backend_root()))
    source_sheet = parsed_statement.account_number or parsed_statement.account_name or "AIB"

    replaced_transactions = 0
    existing_row_numbers: set[int] = set()

    if replace_existing:
        delete_result = await db.execute(
            delete(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.source_type == "bank_statement",
                Transaction.source_file == source_file,
                Transaction.source_sheet == source_sheet,
            )
        )
        replaced_transactions = delete_result.rowcount or 0
    else:
        existing_result = await db.execute(
            select(Transaction.row_number).where(
                Transaction.user_id == user_id,
                Transaction.source_type == "bank_statement",
                Transaction.source_file == source_file,
                Transaction.source_sheet == source_sheet,
            )
        )
        existing_row_numbers = set(existing_result.scalars().all())

    imported_transactions = 0
    skipped_transactions = 0
    transaction_dates = []
    pubs: set[str] = set()
    rules = await load_transaction_rules(db=db, user_id=user_id, source_type="bank_statement")

    for parsed_transaction in parsed_statement.transactions:
        if parsed_transaction.row_number in existing_row_numbers:
            skipped_transactions += 1
            continue

        transaction_dates.append(parsed_transaction.transaction_date)
        if parsed_statement.pub:
            pubs.add(parsed_statement.pub)

        transaction = Transaction(
            user_id=user_id,
            source_type="bank_statement",
            source_file=source_file,
            source_sheet=source_sheet,
            row_number=parsed_transaction.row_number,
            posted_account=_format_posted_account(parsed_statement),
            pub=parsed_statement.pub,
            transaction_date=parsed_transaction.transaction_date,
            description1=parsed_transaction.detail,
            description2=parsed_transaction.references[0] if parsed_transaction.references else None,
            debit_amount=parsed_transaction.debit_amount,
            credit_amount=parsed_transaction.credit_amount,
            transaction_type="Debit" if parsed_transaction.debit_amount is not None else "Credit",
            category=None,
            resale_23_amount=None,
            non_resale_23_amount=None,
            non_resale_13_5_amount=None,
            non_resale_9_amount=None,
            non_resale_0_amount=None,
            annotation_types=[],
            annotation_notes=[],
            has_linked_annotation=False,
            raw_row_json=_serialize_raw_transaction(parsed_statement, parsed_transaction),
        )
        matched_rule = find_matching_transaction_rule(transaction=transaction, rules=rules)
        if matched_rule is not None and apply_transaction_rule(transaction=transaction, rule=matched_rule) is not None:
            transaction.reviewed_at = datetime.utcnow()
        db.add(transaction)
        imported_transactions += 1

    await db.flush()

    return BankStatementImportResult(
        statement_path=source_file,
        account_name=parsed_statement.account_name,
        account_number=parsed_statement.account_number,
        provider=parsed_statement.provider,
        imported_transactions=imported_transactions,
        replaced_transactions=replaced_transactions,
        skipped_transactions=skipped_transactions,
        annotation_count=0,
        first_transaction_date=min(transaction_dates) if transaction_dates else None,
        last_transaction_date=max(transaction_dates) if transaction_dates else None,
        pubs=sorted(pubs),
    )


def _format_posted_account(parsed_statement: ParsedBankStatement) -> str | None:
    if parsed_statement.sort_code and parsed_statement.account_number:
        return f"{parsed_statement.sort_code} - {parsed_statement.account_number}"
    return parsed_statement.account_number or parsed_statement.sort_code


def _serialize_raw_transaction(
    parsed_statement: ParsedBankStatement,
    parsed_transaction,
) -> dict:
    return {
        "provider": parsed_statement.provider,
        "account_name": parsed_statement.account_name,
        "account_number": parsed_statement.account_number,
        "sort_code": parsed_statement.sort_code,
        "page_number": parsed_transaction.page_number,
        "detail": parsed_transaction.detail,
        "balance": str(parsed_transaction.balance) if parsed_transaction.balance is not None else None,
        "references": list(parsed_transaction.references),
        "notes": list(parsed_transaction.notes),
        "transaction_posted_date": (
            parsed_transaction.transaction_posted_date.isoformat()
            if parsed_transaction.transaction_posted_date is not None
            else None
        ),
    }
