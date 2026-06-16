"""Import Bank of Ireland CSV transaction exports.

BOI exports are *cumulative*: each file starts at a fixed from-date and runs to
whenever it was downloaded, so successive files heavily overlap. We therefore
dedupe on transaction content (account + date + descriptions + amounts +
running balance) against what is already stored, so re-importing overlapping
files — or the same file twice — never creates duplicates.

CSV columns (BOI):
  Posted Account, Posted Transactions Date, Description1, Description2,
  Description3, Debit Amount, Credit Amount, Balance, Posted Currency,
  Transaction Type, Local Currency Amount, Local Currency
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.services.transaction_rules import (
    apply_transaction_rule,
    find_matching_transaction_rule,
    load_transaction_rules,
)

# Known Careys Bar Ltd accounts -> pub. The account number is the part after
# the sort/branch code in "932264 - 53747031".
ACCOUNT_PUB: dict[str, str] = {
    "53747031": "Careys",
    "53747114": "Canal",
}

SOURCE_FILE = "bank-csv"  # stable logical ledger so weekly uploads accumulate


@dataclass(slots=True)
class _Row:
    account_number: str
    posted_account: str
    pub: str | None
    transaction_date: date
    description1: str | None
    description2: str | None
    description3: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    balance: Decimal | None
    transaction_type: str | None


@dataclass(slots=True)
class BoiCsvImportResult:
    files: list[str] = field(default_factory=list)
    imported_transactions: int = 0
    duplicate_transactions: int = 0
    accounts: dict[str, int] = field(default_factory=dict)  # pub/account -> imported
    first_transaction_date: date | None = None
    last_transaction_date: date | None = None


def _parse_amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("\xa0", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d/%m/%Y").date()


def _account_number(posted_account: str) -> str:
    # "932264 - 53747031" -> "53747031"
    return posted_account.split("-")[-1].strip()


def _content_key(
    account_number: str,
    transaction_date: date,
    description1: str | None,
    description2: str | None,
    debit: Decimal | None,
    credit: Decimal | None,
    balance: Decimal | None,
) -> tuple:
    return (
        account_number,
        transaction_date.isoformat(),
        (description1 or "").strip(),
        (description2 or "").strip(),
        str(debit) if debit is not None else "",
        str(credit) if credit is not None else "",
        str(balance) if balance is not None else "",
    )


def parse_boi_csv(content: str) -> list[_Row]:
    reader = csv.reader(io.StringIO(content))
    rows: list[_Row] = []
    for raw in reader:
        if not raw or len(raw) < 8:
            continue
        posted_account = (raw[0] or "").strip()
        # Skip the header row and any stray blank lines.
        if not posted_account or posted_account.lower().startswith("posted account"):
            continue
        try:
            transaction_date = _parse_date(raw[1])
        except (ValueError, IndexError):
            continue
        account_number = _account_number(posted_account)
        rows.append(
            _Row(
                account_number=account_number,
                posted_account=posted_account,
                pub=ACCOUNT_PUB.get(account_number),
                transaction_date=transaction_date,
                description1=(raw[2] or "").strip() or None,
                description2=(raw[3] or "").strip() or None,
                description3=(raw[4] or "").strip() or None,
                debit_amount=_parse_amount(raw[5]),
                credit_amount=_parse_amount(raw[6]),
                balance=_parse_amount(raw[7]),
                transaction_type=(raw[9].strip() if len(raw) > 9 and raw[9] else None),
            )
        )
    return rows


async def import_boi_csv_files(
    *,
    db: AsyncSession,
    user_id,
    files: list[tuple[str, str]],  # (filename, text content)
    only_accounts: set[str] | None = None,
) -> BoiCsvImportResult:
    """Parse and import BOI CSV exports, deduping by transaction content against
    what is already stored. `only_accounts` (account numbers) optionally limits
    which accounts are imported (e.g. Careys-only)."""
    result = BoiCsvImportResult()

    parsed_rows: list[_Row] = []
    for name, content in files:
        result.files.append(name)
        for row in parse_boi_csv(content):
            if only_accounts and row.account_number not in only_accounts:
                continue
            parsed_rows.append(row)

    if not parsed_rows:
        return result

    accounts = {row.account_number for row in parsed_rows}

    # Existing content keys + the next row_number per account ledger.
    existing_keys: set[tuple] = set()
    next_row_number: dict[str, int] = {}
    for account_number in accounts:
        existing_result = await db.execute(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.source_type == "bank_statement",
                Transaction.source_file == SOURCE_FILE,
                Transaction.source_sheet == account_number,
            )
        )
        existing = list(existing_result.scalars().all())
        for txn in existing:
            balance = _parse_amount((txn.raw_row_json or {}).get("balance"))
            existing_keys.add(
                _content_key(
                    account_number,
                    txn.transaction_date,
                    txn.description1,
                    txn.description2,
                    txn.debit_amount,
                    txn.credit_amount,
                    balance,
                )
            )
        max_row = await db.execute(
            select(func.max(Transaction.row_number)).where(
                Transaction.user_id == user_id,
                Transaction.source_type == "bank_statement",
                Transaction.source_file == SOURCE_FILE,
                Transaction.source_sheet == account_number,
            )
        )
        next_row_number[account_number] = (max_row.scalar() or 0) + 1

    rules = await load_transaction_rules(db=db, user_id=user_id, source_type="bank_statement")
    seen_in_batch: set[tuple] = set()
    transaction_dates: list[date] = []

    for row in parsed_rows:
        key = _content_key(
            row.account_number,
            row.transaction_date,
            row.description1,
            row.description2,
            row.debit_amount,
            row.credit_amount,
            row.balance,
        )
        if key in existing_keys or key in seen_in_batch:
            result.duplicate_transactions += 1
            continue
        seen_in_batch.add(key)

        row_number = next_row_number[row.account_number]
        next_row_number[row.account_number] = row_number + 1

        transaction = Transaction(
            user_id=user_id,
            source_type="bank_statement",
            source_file=SOURCE_FILE,
            source_sheet=row.account_number,
            row_number=row_number,
            posted_account=row.posted_account,
            pub=row.pub,
            transaction_date=row.transaction_date,
            description1=row.description1,
            description2=row.description2,
            debit_amount=row.debit_amount,
            credit_amount=row.credit_amount,
            transaction_type=row.transaction_type
            or ("Debit" if row.debit_amount is not None else "Credit"),
            category=None,
            annotation_types=[],
            annotation_notes=[],
            has_linked_annotation=False,
            raw_row_json={
                "provider": "BOI",
                "posted_account": row.posted_account,
                "account_number": row.account_number,
                "description3": row.description3,
                "balance": str(row.balance) if row.balance is not None else None,
                "transaction_type": row.transaction_type,
            },
        )
        matched_rule = find_matching_transaction_rule(transaction=transaction, rules=rules)
        if matched_rule is not None and apply_transaction_rule(transaction=transaction, rule=matched_rule) is not None:
            transaction.reviewed_at = datetime.utcnow()
        db.add(transaction)

        result.imported_transactions += 1
        label = row.pub or row.account_number
        result.accounts[label] = result.accounts.get(label, 0) + 1
        transaction_dates.append(row.transaction_date)

    await db.flush()
    if transaction_dates:
        result.first_transaction_date = min(transaction_dates)
        result.last_transaction_date = max(transaction_dates)
    return result
