from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

import pdfplumber


_SORT_CODE_RE = re.compile(r"\b\d{2}-\d{2}-\d{2}\b")
_ACCOUNT_NUMBER_RE = re.compile(r"\b\d{5}-\d{3}\b")
_DATE_PREFIX_RE = re.compile(r"^(?P<day>\d{1,2}) (?P<month>[A-Za-z]{3}) (?P<year>\d{4})$")
_TXN_DATE_RE = re.compile(r"TxnDate:\s*(?P<txn_date>\d{1,2}[A-Za-z]{3}\d{4})", re.IGNORECASE)
_FOOTER_MARKERS = (
    "FOR IMPORTANT INFORMATION",
    "WWW.AIB.IE/STANDARDCONDITIONS",
    "YOUR AUTHORISED LIMIT IS SUBJECT TO THE TERMS AND CONDITIONS",
    "INCLUDING ANY SET-OFF",
    "OVERDRAWN BALANCES ARE MARKED",
    "THANK YOU FOR BANKING WITH US.",
    "ALLIED IRISH BANKS, P.L.C. IS REGULATED BY",
)

_DETAIL_MIN_X = 75.0
_DEBIT_MIN_X = 250.0
_CREDIT_MIN_X = 313.0
_BALANCE_MIN_X = 369.0
_RIGHT_MARGIN_MIN_X = 430.0


@dataclass(slots=True)
class ParsedBankStatementLine:
    page_number: int
    date_text: str | None
    detail_text: str | None
    debit_text: str | None
    credit_text: str | None
    balance_text: str | None
    right_text: str | None = None


@dataclass(slots=True)
class ParsedBankStatementTransaction:
    row_number: int
    page_number: int
    transaction_date: date
    detail: str
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    balance: Decimal | None
    transaction_posted_date: date | None = None
    references: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedBankStatement:
    statement_path: Path
    provider: str
    account_name: str | None
    account_number: str | None
    sort_code: str | None
    pub: str | None
    transactions: list[ParsedBankStatementTransaction]


def parse_aib_bank_statement_pdf(statement_path: str | Path) -> ParsedBankStatement:
    statement_path = Path(statement_path)
    with pdfplumber.open(statement_path) as pdf:
        lines = _extract_lines(pdf)
        account_name = _extract_account_name(lines)
        account_number = _extract_account_number(lines)
        sort_code = _extract_sort_code(lines)

    return parse_aib_bank_statement_lines(
        statement_path=statement_path,
        account_name=account_name,
        account_number=account_number,
        sort_code=sort_code,
        lines=lines,
    )


def parse_aib_bank_statement_lines(
    *,
    statement_path: str | Path,
    account_name: str | None,
    account_number: str | None,
    sort_code: str | None,
    lines: list[ParsedBankStatementLine],
) -> ParsedBankStatement:
    statement_path = Path(statement_path)
    transactions: list[ParsedBankStatementTransaction] = []
    current_statement_date: date | None = None
    current_transaction: ParsedBankStatementTransaction | None = None
    next_row_number = 1

    for line in lines:
        date_prefix = _parse_statement_date(line.date_text)
        if date_prefix is not None:
            current_statement_date = date_prefix

        detail_text = (line.detail_text or "").strip()
        upper_detail = detail_text.upper()
        debit_amount = _parse_decimal(line.debit_text)
        credit_amount = _parse_decimal(line.credit_text)
        has_amount = debit_amount is not None or credit_amount is not None
        combined_text = " ".join(
            part.strip()
            for part in (
                line.date_text,
                line.detail_text,
                line.debit_text,
                line.credit_text,
                line.balance_text,
            )
            if part and part.strip()
        ).upper()

        if any(marker in combined_text for marker in _FOOTER_MARKERS):
            if current_transaction is not None:
                transactions.append(current_transaction)
                current_transaction = None
            continue

        if date_prefix is not None and current_transaction is not None:
            if upper_detail.startswith("BALANCE FORWARD") or not has_amount:
                transactions.append(current_transaction)
                current_transaction = None

        if upper_detail.startswith("BALANCE FORWARD"):
            continue

        if date_prefix is not None and not has_amount:
            continue

        if has_amount:
            if current_statement_date is None or not detail_text:
                continue
            if current_transaction is not None:
                transactions.append(current_transaction)

            current_transaction = ParsedBankStatementTransaction(
                row_number=next_row_number,
                page_number=line.page_number,
                transaction_date=current_statement_date,
                detail=detail_text,
                debit_amount=debit_amount,
                credit_amount=credit_amount,
                balance=_parse_decimal(line.balance_text),
            )
            next_row_number += 1
            continue

        if current_transaction is None or not detail_text:
            continue

        txn_date = _parse_txn_date(detail_text)
        if txn_date is not None:
            current_transaction.transaction_posted_date = txn_date
        elif detail_text not in current_transaction.references:
            current_transaction.references.append(detail_text)

        if line.balance_text is not None:
            current_transaction.balance = _parse_decimal(line.balance_text)

        if txn_date is None and detail_text not in current_transaction.notes:
            current_transaction.notes.append(detail_text)

    if current_transaction is not None:
        transactions.append(current_transaction)

    return ParsedBankStatement(
        statement_path=statement_path,
        provider="aib",
        account_name=account_name,
        account_number=account_number,
        sort_code=sort_code,
        pub=_infer_pub(account_name),
        transactions=transactions,
    )


def _extract_lines(pdf) -> list[ParsedBankStatementLine]:
    extracted_lines: list[ParsedBankStatementLine] = []
    for page_index, page in enumerate(pdf.pages, start=1):
        words = page.extract_words(
            x_tolerance=1,
            y_tolerance=2,
            keep_blank_chars=False,
            use_text_flow=False,
        )
        for line_words in _group_words_into_lines(words):
            main_words = [word for word in line_words if word["x0"] < _RIGHT_MARGIN_MIN_X]
            if not main_words:
                continue

            extracted_lines.append(
                ParsedBankStatementLine(
                    page_number=page_index,
                    date_text=_join_words(
                        [
                            word
                            for word in main_words
                            if word["x0"] < _DETAIL_MIN_X
                        ]
                    )
                    or None,
                    detail_text=_join_words(
                        [
                            word
                            for word in main_words
                            if _DETAIL_MIN_X <= word["x0"] < _DEBIT_MIN_X
                        ]
                    )
                    or None,
                    debit_text=_join_words(
                        [
                            word
                            for word in main_words
                            if _DEBIT_MIN_X <= word["x0"] < _CREDIT_MIN_X
                        ]
                    )
                    or None,
                    credit_text=_join_words(
                        [
                            word
                            for word in main_words
                            if _CREDIT_MIN_X <= word["x0"] < _BALANCE_MIN_X
                        ]
                    )
                    or None,
                    balance_text=_join_words(
                        [
                            word
                            for word in main_words
                            if _BALANCE_MIN_X <= word["x0"] < _RIGHT_MARGIN_MIN_X
                        ]
                    )
                    or None,
                    right_text=_join_words(
                        [
                            word
                            for word in line_words
                            if word["x0"] >= _RIGHT_MARGIN_MIN_X
                        ]
                    )
                    or None,
                )
            )
    return extracted_lines


def _group_words_into_lines(words: list[dict]) -> list[list[dict]]:
    sorted_words = sorted(words, key=lambda word: (word["top"], word["x0"]))
    lines: list[list[dict]] = []

    for word in sorted_words:
        if not lines:
            lines.append([word])
            continue
        current_line = lines[-1]
        current_top = current_line[0]["top"]
        if abs(word["top"] - current_top) <= 2:
            current_line.append(word)
            continue
        lines.append([word])

    return lines


def _extract_sort_code(lines: list[ParsedBankStatementLine]) -> str | None:
    for line in lines[:40]:
        for candidate in (line.credit_text, line.balance_text, line.detail_text, line.date_text):
            if not candidate:
                continue
            match = _SORT_CODE_RE.search(candidate)
            if match:
                return match.group(0)
    return None


def _extract_account_number(lines: list[ParsedBankStatementLine]) -> str | None:
    for line in lines[:40]:
        for candidate in (
            line.right_text,
            line.balance_text,
            line.credit_text,
            line.debit_text,
            line.detail_text,
        ):
            if not candidate:
                continue
            match = _ACCOUNT_NUMBER_RE.search(candidate)
            if match:
                return match.group(0)
    return None


def _extract_account_name(lines: list[ParsedBankStatementLine]) -> str | None:
    for line in lines[:40]:
        account_text = (line.right_text or "").strip()
        if not account_text:
            continue
        upper_text = account_text.upper()
        if "ACCOUNT NAME" in upper_text or "DATE OF STATEMENT" in upper_text:
            continue
        if "LTD" in upper_text or "LIMITED" in upper_text:
            return account_text
    return None


def _parse_statement_date(value: str | None) -> date | None:
    if not value:
        return None
    match = _DATE_PREFIX_RE.match(value.strip())
    if match is None:
        return None
    return datetime.strptime(match.group(0), "%d %b %Y").date()


def _parse_txn_date(value: str) -> date | None:
    match = _TXN_DATE_RE.search(value)
    if match is None:
        return None
    return datetime.strptime(match.group("txn_date"), "%d%b%Y").date()


def _parse_decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    cleaned = value.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _join_words(words: list[dict]) -> str:
    return " ".join(word["text"] for word in sorted(words, key=lambda item: item["x0"])).strip()


def _infer_pub(account_name: str | None) -> str | None:
    if not account_name:
        return None
    normalized = account_name.upper().replace("'", "")
    normalized = re.sub(r"[^A-Za-z0-9 ]+", " ", normalized)
    normalized = re.sub(r"\b(BAR|LTD|LIMITED)\b", " ", normalized)
    collapsed = " ".join(normalized.split())
    if not collapsed:
        return None
    return collapsed.title()
