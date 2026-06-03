from __future__ import annotations

from dataclasses import dataclass
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, TransactionRule

RULE_MATCH_FIELD_COUNTERPARTY = "description1_counterparty"
RULE_REVIEW_STATUS_HANDLED = "handled_by_rule"
STANDARD_TRANSACTION_CATEGORIES = (
    "Wages",
    "Contract",
    "Hard Copy Available",
    "No Document Expected",
    "Invoice Match",
    "Statement Settlement",
)
STANDARD_REVIEW_STATUS_CATEGORIES = {
    "linked": "Invoice Match",
    "supporting_docs_only": "Statement Settlement",
    "hard_copy_available": "Hard Copy Available",
    "no_document_expected": "No Document Expected",
}
RULE_CATEGORY_PRESETS = {
    "Wages": {
        "review_status": RULE_REVIEW_STATUS_HANDLED,
        "document_expectation": "none",
        "default_note": "Wages / payroll",
    },
    "Contract": {
        "review_status": RULE_REVIEW_STATUS_HANDLED,
        "document_expectation": "annual_invoice",
        "default_note": "Charged monthly, invoiced annually",
    },
    "Hard Copy Available": {
        "review_status": "hard_copy_available",
        "document_expectation": "hard_copy",
        "default_note": "Hard copy available",
    },
    "No Document Expected": {
        "review_status": "no_document_expected",
        "document_expectation": "none",
        "default_note": "No supplier document expected",
    },
}
VALID_RULE_REVIEW_STATUSES = {
    RULE_REVIEW_STATUS_HANDLED,
    "no_document_expected",
    "hard_copy_available",
}
VALID_DOCUMENT_EXPECTATIONS = {
    "none",
    "hard_copy",
    "annual_invoice",
    "monthly_invoice",
    "statement",
    "unknown",
}

BANK_STATEMENT_COUNTERPARTY_PREFIX_PATTERN = re.compile(
    r"^(?:\*?(?:inet|mobi|pos|visa|mc|card)\s+|(?:d/d|dd|vdp|vdc)\s*[- ]*)",
    re.IGNORECASE,
)
NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class AppliedTransactionRule:
    rule: TransactionRule
    category_changed: bool = False
    status_changed: bool = False
    supplier_changed: bool = False
    note_changed: bool = False


def normalize_transaction_category(value: str | None) -> str | None:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return None
    for category in STANDARD_TRANSACTION_CATEGORIES:
        if cleaned.lower() == category.lower():
            return category
    return cleaned


def standard_category_for_review_status(review_status: str | None) -> str | None:
    if not review_status:
        return None
    return STANDARD_REVIEW_STATUS_CATEGORIES.get(review_status)


def default_rule_preset(category: str | None) -> dict | None:
    normalized = normalize_transaction_category(category)
    if not normalized:
        return None
    return RULE_CATEGORY_PRESETS.get(normalized)


def clean_transaction_counterparty(source_type: str | None, value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).split()).strip()
    if not cleaned:
        return None
    if (source_type or "").lower() == "bank_statement":
        cleaned = BANK_STATEMENT_COUNTERPARTY_PREFIX_PATTERN.sub("", cleaned).strip(" -")
    return cleaned or None


def compact_rule_match_value(source_type: str | None, value: str | None) -> str | None:
    cleaned = clean_transaction_counterparty(source_type, value)
    if not cleaned:
        return None
    return NON_ALNUM_PATTERN.sub("", cleaned.lower()) or None


async def load_transaction_rules(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    source_type: str | None = None,
) -> list[TransactionRule]:
    query = select(TransactionRule).where(
        TransactionRule.user_id == user_id,
        TransactionRule.is_active.is_(True),
    )
    if source_type:
        query = query.where(TransactionRule.source_type == source_type)
    result = await db.execute(query.order_by(TransactionRule.updated_at.desc(), TransactionRule.created_at.desc()))
    return list(result.scalars().all())


def find_matching_transaction_rule(
    *,
    transaction: Transaction,
    rules: list[TransactionRule],
) -> TransactionRule | None:
    candidates = matching_transaction_rules(
        transaction=transaction,
        rules=rules,
    )
    if not candidates:
        return None

    candidates.sort(
        key=lambda rule: (
            0 if rule.pub == transaction.pub and transaction.pub else 1,
            0 if rule.display_label else 1,
        )
    )
    return candidates[0]


def matching_transaction_rules(
    *,
    transaction: Transaction,
    rules: list[TransactionRule],
) -> list[TransactionRule]:
    match_value = compact_rule_match_value(transaction.source_type, transaction.description1)
    if not match_value:
        return []

    source_type = (transaction.source_type or "").lower() or None
    return [
        rule
        for rule in rules
        if rule.match_field == RULE_MATCH_FIELD_COUNTERPARTY
        and rule.match_value == match_value
        and ((rule.source_type or "").lower() == source_type)
        and (rule.pub is None or rule.pub == transaction.pub)
    ]


def copy_transaction_rule_fields(
    *,
    source_rule: TransactionRule,
    target_rule: TransactionRule,
    display_label: str | None = None,
) -> None:
    target_rule.display_label = display_label or source_rule.display_label
    target_rule.category_override = normalize_transaction_category(source_rule.category_override)
    target_rule.review_status = source_rule.review_status
    target_rule.expected_supplier = source_rule.expected_supplier
    target_rule.document_expectation = source_rule.document_expectation
    target_rule.owner_note = source_rule.owner_note
    target_rule.is_active = True


def apply_transaction_rule(
    *,
    transaction: Transaction,
    rule: TransactionRule,
    force: bool = False,
) -> AppliedTransactionRule | None:
    if not force and transaction.review_status in {
        "linked",
        "supporting_docs_only",
        "hard_copy_available",
        "handled_by_rule",
        "no_document_expected",
    }:
        return None

    applied = AppliedTransactionRule(rule=rule)

    target_category = normalize_transaction_category(rule.category_override)
    if not target_category:
        target_category = standard_category_for_review_status(rule.review_status)
    if target_category and transaction.category != target_category:
        transaction.category = target_category
        applied.category_changed = True
    if transaction.review_status != rule.review_status:
        transaction.review_status = rule.review_status
        applied.status_changed = True
    if rule.expected_supplier and transaction.expected_supplier != rule.expected_supplier:
        transaction.expected_supplier = rule.expected_supplier
        applied.supplier_changed = True
    if rule.owner_note and transaction.review_note != rule.owner_note:
        transaction.review_note = rule.owner_note
        applied.note_changed = True

    if not any(
        [
            applied.category_changed,
            applied.status_changed,
            applied.supplier_changed,
            applied.note_changed,
        ]
    ):
        return None

    return applied
