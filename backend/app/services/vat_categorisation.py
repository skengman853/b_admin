"""VAT book categorisation — Stage A.

Learns (description + pub -> category) rules from the operator's existing
categorised transactions (the hand-made VAT book, imported as vatbook rows),
and predicts the category + VAT band for any transaction. This is the engine
that turns reconciled bank transactions into VAT-book rows.

Rules are learned in-memory from the data already in the database; nothing
sensitive is committed to the repo. The matched-document supplier (when present)
strengthens resale predictions.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.models import Transaction

# VAT band <-> the Transaction amount column that holds it.
VAT_BANDS = (
    ("resale_23", "Resale @ 23%", "resale_23_amount"),
    ("non_resale_23", "Non-Resale @ 23%", "non_resale_23_amount"),
    ("non_resale_13_5", "Non-Resale @ 13.5%", "non_resale_13_5_amount"),
    ("non_resale_9", "Non-Resale @ 9%", "non_resale_9_amount"),
    ("non_resale_0", "Non-Resale @ 0%", "non_resale_0_amount"),
)
BAND_COLUMN = {key: column for key, _, column in VAT_BANDS}
BAND_LABEL = {key: label for key, label, _ in VAT_BANDS}
BAND_KEYS = tuple(key for key, _, _ in VAT_BANDS)
_BAND_COLUMN = BAND_COLUMN
_BAND_LABEL = BAND_LABEL


def set_transaction_category(transaction: Transaction, *, category: str, band: str | None) -> None:
    """Apply an operator category decision: set category, mark confirmed, and
    place the gross debit into the chosen VAT band (clearing the others)."""
    transaction.category = category
    transaction.category_confirmed = True
    gross = transaction.debit_amount
    for key, _, column in VAT_BANDS:
        setattr(transaction, column, gross if (band == key and gross is not None) else None)

_PREFIXES = (
    "d/d ", "vdc-", "vdp-", "pos ", "*inet ", "paymentsense", "lodgment", "lodgement",
)


def normalize_description(value: str | None) -> str:
    text = (value or "").upper().strip()
    for prefix in _PREFIXES:
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    text = re.sub(r"\b[A-Z]{2}\d+\b", "", text)  # IBAN / country-code references
    text = re.sub(r"\d", "", text)
    return re.sub(r"\s+", " ", text).strip()[:16]


def transaction_band(transaction: Transaction) -> str | None:
    for key, _, column in VAT_BANDS:
        if getattr(transaction, column) is not None:
            return key
    return None


def band_label(band: str | None) -> str | None:
    return _BAND_LABEL.get(band) if band else None


@dataclass(slots=True)
class CategoryRuleset:
    # (normalized description, pub) -> category
    by_description: dict[tuple[str, str | None], str]
    # category -> most common VAT band
    category_band: dict[str, str]
    # (normalized supplier, pub) -> resale category, parsed from category names
    resale_by_supplier: dict[tuple[str, str | None], str]

    def category_count(self) -> int:
        return len(set(self.by_description.values()))


def _resale_supplier_pub(category: str) -> tuple[str, str | None] | None:
    # "Resale - Diageo - Careys" -> ("DIAGEO", "Careys")
    if not category.lower().startswith("resale"):
        return None
    parts = [p.strip() for p in category.split(" - ")]
    if len(parts) < 2:
        return None
    supplier = normalize_description(parts[1])
    pub = parts[2] if len(parts) >= 3 else None
    return (supplier, pub)


def learn_ruleset(training: list[Transaction]) -> CategoryRuleset:
    desc_votes: dict[tuple[str, str | None], Counter] = defaultdict(Counter)
    band_votes: dict[str, Counter] = defaultdict(Counter)
    resale: dict[tuple[str, str | None], str] = {}
    for txn in training:
        if not txn.category:
            continue
        desc_votes[(normalize_description(txn.description1), txn.pub)][txn.category] += 1
        band = transaction_band(txn)
        if band:
            band_votes[txn.category][band] += 1
        supplier_pub = _resale_supplier_pub(txn.category)
        if supplier_pub:
            resale[supplier_pub] = txn.category
    return CategoryRuleset(
        by_description={k: votes.most_common(1)[0][0] for k, votes in desc_votes.items()},
        category_band={c: votes.most_common(1)[0][0] for c, votes in band_votes.items()},
        resale_by_supplier=resale,
    )


@dataclass(slots=True)
class VatPrediction:
    category: str | None
    band: str | None
    source: str  # "matched_supplier" | "learned_rule" | "unknown"


def predict(
    transaction: Transaction,
    ruleset: CategoryRuleset,
    *,
    matched_supplier: str | None = None,
) -> VatPrediction:
    # A matched drink supplier is the strongest resale signal: the operator's
    # own taxonomy already has "Resale - <supplier> - <pub>" rows, so prefer the
    # learned category for that supplier+pub when a document confirms it.
    if matched_supplier:
        resale_category = ruleset.resale_by_supplier.get(
            (normalize_description(matched_supplier), transaction.pub)
        )
        if resale_category:
            return VatPrediction(resale_category, ruleset.category_band.get(resale_category), "matched_supplier")

    category = ruleset.by_description.get((normalize_description(transaction.description1), transaction.pub))
    if category is None:
        return VatPrediction(None, None, "unknown")
    return VatPrediction(category, ruleset.category_band.get(category), "learned_rule")


@dataclass(slots=True)
class VatBookRow:
    transaction_id: object
    transaction_date: object
    pub: str | None
    description: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    predicted_category: str | None
    predicted_band: str | None
    predicted_band_label: str | None
    source: str
    actual_category: str | None
    actual_band: str | None
    category_correct: bool | None  # None when no ground truth to compare
    confirmed: bool = False


def build_vat_book(
    *,
    targets: list[Transaction],
    ruleset: CategoryRuleset,
    supplier_by_transaction: dict | None = None,
) -> list[VatBookRow]:
    supplier_by_transaction = supplier_by_transaction or {}
    rows: list[VatBookRow] = []
    for txn in targets:
        prediction = predict(
            txn, ruleset, matched_supplier=supplier_by_transaction.get(txn.id)
        )
        actual_category = txn.category or None
        category_correct = (
            (prediction.category == actual_category) if actual_category else None
        )
        rows.append(
            VatBookRow(
                transaction_id=txn.id,
                transaction_date=txn.transaction_date,
                pub=txn.pub,
                description=" ".join(p for p in (txn.description1, txn.description2) if p) or None,
                debit_amount=txn.debit_amount,
                credit_amount=txn.credit_amount,
                predicted_category=prediction.category,
                predicted_band=prediction.band,
                predicted_band_label=band_label(prediction.band),
                source=prediction.source,
                actual_category=actual_category,
                actual_band=transaction_band(txn),
                category_correct=category_correct,
                confirmed=bool(getattr(txn, "category_confirmed", False)),
            )
        )
    return rows
