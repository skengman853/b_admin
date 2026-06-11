from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ARITHMETIC_MODE_ACTIVITY = "activity"
ARITHMETIC_MODE_OPEN_ITEM = "open_item"
ARITHMETIC_MODE_NOT_APPLICABLE = "not_applicable"

ARITHMETIC_BALANCED = "balanced"
ARITHMETIC_UNBALANCED = "unbalanced"
ARITHMETIC_INSUFFICIENT_DATA = "insufficient_data"
ARITHMETIC_NOT_APPLICABLE = "not_applicable"

ROW_KIND_INVOICE = "invoice"
ROW_KIND_CREDIT_NOTE = "credit_note"
ROW_KIND_PAYMENT = "payment"
ROW_KIND_DISCOUNT = "discount"
ROW_KIND_BALANCE_FORWARD = "balance_forward"
ROW_KIND_OTHER = "other"

AMOUNT_TOLERANCE = Decimal("0.01")


def amounts_match(left: Decimal | None, right: Decimal | None) -> bool:
    """Single tolerance rule for amount comparison across matching and verification."""
    if left is None or right is None:
        return False
    return abs(left - right) <= AMOUNT_TOLERANCE

NON_SETTLEMENT_STATEMENT_KIND_PREFIXES = (
    "sub_account",
    "keg_flow",
)


def is_non_settlement_statement_kind(statement_kind: str | None) -> bool:
    normalized = (statement_kind or "").strip().lower().replace(" ", "_").replace("-", "_")
    return normalized.startswith(NON_SETTLEMENT_STATEMENT_KIND_PREFIXES)


@dataclass(slots=True)
class ArithmeticRow:
    kind: str
    amount: Decimal | None
    event_date: date | None = None


@dataclass(slots=True)
class StatementArithmeticResult:
    mode: str
    status: str
    delta: Decimal | None = None
    checks: list[str] = field(default_factory=list)

    @property
    def is_balanced(self) -> bool:
        return self.status == ARITHMETIC_BALANCED

    @property
    def is_unbalanced(self) -> bool:
        return self.status == ARITHMETIC_UNBALANCED


BALANCE_FORWARD_TOKENS = {"bfwd", "bf", "balanceforward", "broughtforward", "openingbalance", "balancebf"}


def classify_statement_row_kind(transaction_type: str | None, *, reference: str | None = None) -> str:
    reference_normalized = "".join(ch for ch in (reference or "").lower() if ch.isalnum())
    if reference_normalized in BALANCE_FORWARD_TOKENS:
        return ROW_KIND_BALANCE_FORWARD

    raw = (transaction_type or "").strip().lower()
    if not raw:
        return ROW_KIND_OTHER
    if raw.startswith("dd-"):
        return ROW_KIND_PAYMENT

    normalized = "".join(ch for ch in raw if ch.isalnum())
    if not normalized:
        return ROW_KIND_OTHER
    if normalized in BALANCE_FORWARD_TOKENS or "balanceforward" in normalized or "broughtforward" in normalized:
        return ROW_KIND_BALANCE_FORWARD
    if normalized in {"invoice", "invoic", "inv"} or "invoic" in normalized:
        return ROW_KIND_INVOICE
    if (
        normalized in {"crnote", "creditnote", "credit", "crn", "rebate"}
        or "crnote" in normalized
        or "creditnote" in normalized
        or "rebate" in normalized
    ):
        return ROW_KIND_CREDIT_NOTE
    if (
        normalized in {"payment", "paymnt", "pay", "pmt", "receipt", "rec", "rct"}
        or "paymnt" in normalized
        or "receipt" in normalized
    ):
        return ROW_KIND_PAYMENT
    if "disc" in normalized:
        return ROW_KIND_DISCOUNT
    return ROW_KIND_OTHER


def verify_statement_arithmetic(
    *,
    rows: list[ArithmeticRow],
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
    total_due: Decimal | None,
    settlement_discount_total: Decimal | None = None,
    statement_kind: str | None = None,
    period_start: date | None = None,
) -> StatementArithmeticResult:
    if is_non_settlement_statement_kind(statement_kind):
        return StatementArithmeticResult(
            mode=ARITHMETIC_MODE_NOT_APPLICABLE,
            status=ARITHMETIC_NOT_APPLICABLE,
            checks=["statement_kind_exempt_from_arithmetic"],
        )

    # Balance-forward rows restate the opening balance; they carry no activity
    # and are ignored entirely.
    relevant_rows = [row for row in rows if row.kind not in (ROW_KIND_OTHER, ROW_KIND_BALANCE_FORWARD)]
    unclassified_with_amounts = [
        row for row in rows if row.kind == ROW_KIND_OTHER and row.amount is not None
    ]
    rows_missing_amounts = [row for row in relevant_rows if row.amount is None]

    # Statements like Diageo's main ERP layout state an opening balance and a
    # total due, with the total due acting as the closing balance.
    effective_closing = closing_balance
    used_total_due_as_closing = False
    if closing_balance is None and opening_balance is not None and total_due is not None:
        effective_closing = total_due
        used_total_due_as_closing = True

    mode = _select_mode(
        opening_balance=opening_balance,
        closing_balance=effective_closing,
        total_due=total_due,
        rows=relevant_rows,
    )
    if mode is None:
        return StatementArithmeticResult(
            mode=ARITHMETIC_MODE_NOT_APPLICABLE,
            status=ARITHMETIC_INSUFFICIENT_DATA,
            checks=["no_verifiable_control_totals"],
        )

    if rows_missing_amounts:
        return StatementArithmeticResult(
            mode=mode,
            status=ARITHMETIC_INSUFFICIENT_DATA,
            checks=["rows_missing_amounts"],
        )
    if unclassified_with_amounts:
        return StatementArithmeticResult(
            mode=mode,
            status=ARITHMETIC_INSUFFICIENT_DATA,
            checks=["unclassified_rows_with_amounts"],
        )

    # Charge rows dated before the statement period are brought-forward items:
    # their amounts already live inside the opening balance and must not be
    # re-added to the activity sum.
    charge_rows = relevant_rows
    checks: list[str] = []
    if mode == ARITHMETIC_MODE_ACTIVITY and period_start is not None:
        charge_rows = [
            row
            for row in relevant_rows
            if not (
                row.kind in {ROW_KIND_INVOICE, ROW_KIND_CREDIT_NOTE}
                and row.event_date is not None
                and row.event_date < period_start
            )
        ]
        if len(charge_rows) != len(relevant_rows):
            checks.append("brought_forward_rows_excluded")

    invoices = _sum_kind_abs(charge_rows, ROW_KIND_INVOICE)
    credits = _sum_kind_abs(charge_rows, ROW_KIND_CREDIT_NOTE)
    discounts = _sum_kind_abs(relevant_rows, ROW_KIND_DISCOUNT)
    # Payments sum with their signs: a negative payment is a credit application
    # netting off inside the statement (extraction normalizes cash payments to
    # positive upstream, so ordinary rows are unaffected).
    payments = _sum_kind_raw(relevant_rows, ROW_KIND_PAYMENT)

    if mode == ARITHMETIC_MODE_ACTIVITY:
        expected_closing = opening_balance + invoices - credits - payments - discounts
        delta = expected_closing - effective_closing
        checks.append("activity_balance_equation")
        if used_total_due_as_closing:
            checks.append("total_due_used_as_closing")
    else:
        expected_total = invoices - credits - payments - discounts
        delta = expected_total - total_due
        checks.append("open_item_total_equation")

    if (
        closing_balance is not None
        and total_due is not None
        and settlement_discount_total is not None
        and abs((closing_balance - settlement_discount_total) - total_due) <= AMOUNT_TOLERANCE
    ):
        checks.append("total_due_matches_closing_minus_discount")

    status = ARITHMETIC_BALANCED if abs(delta) <= AMOUNT_TOLERANCE else ARITHMETIC_UNBALANCED
    return StatementArithmeticResult(mode=mode, status=status, delta=delta, checks=checks)


def _select_mode(
    *,
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
    total_due: Decimal | None,
    rows: list[ArithmeticRow],
) -> str | None:
    if opening_balance is not None and closing_balance is not None:
        return ARITHMETIC_MODE_ACTIVITY
    if total_due is None or opening_balance is not None:
        return None
    # Pure open-item statements state a total due and no running balances; rows
    # cover each open item's full life, so paid amounts net off inside the sum.
    if closing_balance is None:
        return ARITHMETIC_MODE_OPEN_ITEM
    # Some extractions mirror the same outstanding figure into closing_balance
    # and total_due. Without payment rows the rows are a plain unpaid-items
    # list, which is still verifiable; with payment rows they are period
    # activity against an unknown opening balance, which is not.
    has_payment_rows = any(row.kind == ROW_KIND_PAYMENT for row in rows)
    if closing_balance == total_due and not has_payment_rows:
        return ARITHMETIC_MODE_OPEN_ITEM
    return None


def _sum_kind_abs(rows: list[ArithmeticRow], kind: str) -> Decimal:
    return sum(
        (abs(row.amount) for row in rows if row.kind == kind and row.amount is not None),
        Decimal("0.00"),
    )


def _sum_kind_raw(rows: list[ArithmeticRow], kind: str) -> Decimal:
    return sum(
        (row.amount for row in rows if row.kind == kind and row.amount is not None),
        Decimal("0.00"),
    )
