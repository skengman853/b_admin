from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Document,
    DocumentFinancialRow,
    ReconciliationSuggestion,
    ReconciliationSuggestionItem,
    Transaction,
)
from app.services.document_extraction import EXTRACTION_VERSION
from app.services.document_ledger import (
    LEDGER_ENTRY_CREDIT_NOTE,
    LEDGER_ENTRY_DISCOUNT,
    LEDGER_ENTRY_INVOICE,
    LEDGER_ENTRY_PAYMENT,
    ParsedDocumentLedger,
    ParsedLedgerEntry,
    build_statement_settlements,
)
from app.services.statement_arithmetic import amounts_match

MATCHER_VERSION = "reconciliation_matcher_v1"


@dataclass(slots=True)
class _SuggestionItemSpec:
    item_role: str
    document_id: object | None = None
    financial_row_id: object | None = None
    reference: str | None = None
    amount: Decimal | None = None
    signed_amount: Decimal | None = None


@dataclass(slots=True)
class _SuggestionSpec:
    suggestion_type: str
    confidence_score: float | None
    reason_summary: str | None
    reason_json: dict
    verifier_status: str
    items: list[_SuggestionItemSpec] = field(default_factory=list)


@dataclass(slots=True)
class PersistedSuggestionMatch:
    document_id: object
    document_type: str
    supplier: str
    reference: str | None
    document_date: object | None
    amount: Decimal | None
    vat_amount: Decimal | None
    score: float | None
    reason: str
    storage_state: str = "local_only"
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    drive_file_id: str | None = None
    drive_web_link: str | None = None


@dataclass(slots=True)
class PersistedPrimarySuggestion:
    suggestion_type: str
    status: str
    verifier_status: str | None
    confidence_score: float | None
    reason_summary: str | None
    resolution_bucket: str | None = None
    recommended_review_status: str | None = None
    matcher_status: str | None = None
    item_count: int = 0
    document_count: int = 0
    verifier_reasons: list[str] = field(default_factory=list)


async def sync_reconciliation_suggestions(
    *,
    db: AsyncSession,
    user_id,
    transaction: Transaction,
    analysis,
    candidate_documents: list[Document],
    supporting_documents: list[Document],
    candidate_ledgers: list[ParsedDocumentLedger],
    supporting_ledgers: list[ParsedDocumentLedger],
) -> None:
    specs = _build_suggestion_specs(
        transaction=transaction,
        analysis=analysis,
        candidate_documents=candidate_documents,
        supporting_documents=supporting_documents,
        candidate_ledgers=candidate_ledgers,
        supporting_ledgers=supporting_ledgers,
    )

    existing_result = await db.execute(
        select(ReconciliationSuggestion).where(
            ReconciliationSuggestion.user_id == user_id,
            ReconciliationSuggestion.transaction_id == transaction.id,
            ReconciliationSuggestion.status == "suggested",
        )
    )
    for suggestion in existing_result.scalars().all():
        suggestion.status = "superseded"

    for spec in specs:
        suggestion = ReconciliationSuggestion(
            user_id=user_id,
            transaction_id=transaction.id,
            suggestion_type=spec.suggestion_type,
            status="suggested",
            confidence_score=spec.confidence_score,
            reason_summary=spec.reason_summary,
            reason_json=spec.reason_json,
            verifier_status=spec.verifier_status,
            extractor_version=EXTRACTION_VERSION,
            matcher_version=MATCHER_VERSION,
        )
        suggestion.items = [
            ReconciliationSuggestionItem(
                user_id=user_id,
                document_id=item.document_id,
                financial_row_id=item.financial_row_id,
                item_role=item.item_role,
                reference=item.reference,
                amount=item.amount,
                signed_amount=item.signed_amount,
            )
            for item in _dedupe_item_specs(spec.items)
        ]
        _apply_deterministic_verifier(
            transaction=transaction,
            suggestion=suggestion,
            document_by_id={
                document.id: document
                for document in [*candidate_documents, *supporting_documents]
            },
            financial_row_by_id={
                row.id: row
                for document in [*candidate_documents, *supporting_documents]
                for row in (document.financial_rows or [])
            },
        )
        db.add(suggestion)


def _build_suggestion_specs(
    *,
    transaction: Transaction,
    analysis,
    candidate_documents: list[Document],
    supporting_documents: list[Document],
    candidate_ledgers: list[ParsedDocumentLedger],
    supporting_ledgers: list[ParsedDocumentLedger],
) -> list[_SuggestionSpec]:
    suggestion_specs: list[_SuggestionSpec] = []
    candidate_by_id = {document.id: document for document in candidate_documents}
    supporting_by_id = {document.id: document for document in supporting_documents}
    support_ledger_by_id = {ledger.document_id: ledger for ledger in supporting_ledgers}

    direct_matches = [*analysis.exact_matches, *analysis.suggested_matches]
    if direct_matches:
        suggestion_specs.append(
            _build_direct_invoice_suggestion(
                analysis=analysis,
                document_by_id=candidate_by_id,
                matches=direct_matches,
            )
        )

    if analysis.supporting_matches:
        settlements = _matching_support_settlements(
            transaction=transaction,
            supporting_matches=analysis.supporting_matches,
            ledger_by_id=support_ledger_by_id,
        )
        suggestion_specs.append(
            _build_supporting_suggestion(
                analysis=analysis,
                support_document_by_id=supporting_by_id,
                supporting_matches=analysis.supporting_matches,
                settlements=settlements,
            )
        )

    if analysis.resolution_bucket == "no_document_expected":
        suggestion_specs.append(
            _SuggestionSpec(
                suggestion_type="rule_resolution",
                confidence_score=1.0,
                reason_summary=analysis.resolution_reason or analysis.analysis_note or "No document expected",
                reason_json={
                    "resolution_bucket": analysis.resolution_bucket,
                    "recommended_review_status": analysis.recommended_review_status,
                    "status": analysis.status,
                },
                verifier_status="passed",
            )
        )

    return suggestion_specs


def _build_direct_invoice_suggestion(*, analysis, document_by_id: dict, matches: list) -> _SuggestionSpec:
    items: list[_SuggestionItemSpec] = []
    scores: list[float] = []
    for match in analysis.exact_matches:
        document = document_by_id.get(match.document_id)
        scores.append(match.score or 0.0)
        items.append(
            _SuggestionItemSpec(
                item_role=_exact_item_role(document),
                document_id=match.document_id,
                financial_row_id=_find_document_financial_row_id(
                    document=document,
                    row_type=_row_type_for_document(document),
                    reference=match.reference,
                    amount=match.amount,
                ),
                reference=match.reference,
                amount=match.amount,
                signed_amount=_signed_amount_for_document(document, match.amount),
            )
        )
    for match in analysis.suggested_matches:
        document = document_by_id.get(match.document_id)
        scores.append(match.score or 0.0)
        items.append(
            _SuggestionItemSpec(
                item_role=_suggested_item_role(document),
                document_id=match.document_id,
                financial_row_id=_find_document_financial_row_id(
                    document=document,
                    row_type=_row_type_for_document(document),
                    reference=match.reference,
                    amount=match.amount,
                ),
                reference=match.reference,
                amount=match.amount,
                signed_amount=_signed_amount_for_document(document, match.amount),
            )
        )

    verifier_status = "passed" if analysis.status == "matched" else "partial"
    return _SuggestionSpec(
        suggestion_type="direct_invoice_match",
        confidence_score=max(scores) if scores else None,
        reason_summary=analysis.resolution_reason or analysis.analysis_note or "Direct invoice match available",
        reason_json={
            "resolution_bucket": analysis.resolution_bucket,
            "recommended_review_status": analysis.recommended_review_status,
            "status": analysis.status,
            "exact_match_count": len(analysis.exact_matches),
            "suggested_match_count": len(analysis.suggested_matches),
        },
        verifier_status=verifier_status,
        items=items,
    )


def _build_supporting_suggestion(
    *,
    analysis,
    support_document_by_id: dict,
    supporting_matches: list,
    settlements: list,
) -> _SuggestionSpec:
    items: list[_SuggestionItemSpec] = []
    scores: list[float] = []
    for match in supporting_matches:
        document = support_document_by_id.get(match.document_id)
        scores.append(match.score or 0.0)
        items.append(
            _SuggestionItemSpec(
                item_role="statement" if document and document.document_type == "statement" else "support_doc",
                document_id=match.document_id,
                reference=match.reference,
                amount=match.amount,
                signed_amount=match.amount,
            )
        )

    for settlement in settlements:
        payment_entry = settlement.payment_entry
        items.append(
            _SuggestionItemSpec(
                item_role="payment_row",
                document_id=payment_entry.document_id,
                financial_row_id=_find_financial_row_id_for_entry(
                    document=support_document_by_id.get(payment_entry.document_id),
                    entry=payment_entry,
                ),
                reference=payment_entry.reference,
                amount=payment_entry.amount,
                signed_amount=payment_entry.signed_amount,
            )
        )
        for component in settlement.component_entries:
            items.append(
                _SuggestionItemSpec(
                    item_role=_entry_item_role(component.entry_kind),
                    document_id=component.document_id,
                    financial_row_id=_find_financial_row_id_for_entry(
                        document=support_document_by_id.get(component.document_id),
                        entry=component,
                    ),
                    reference=component.reference,
                    amount=component.amount,
                    signed_amount=component.signed_amount,
                )
            )

    has_settlement = bool(settlements)
    return _SuggestionSpec(
        suggestion_type="statement_settlement" if has_settlement else "supporting_docs_only",
        confidence_score=max(scores) if scores else None,
        reason_summary=analysis.resolution_reason or analysis.analysis_note or "Supporting documents explain the transaction",
        reason_json={
            "resolution_bucket": analysis.resolution_bucket,
            "recommended_review_status": analysis.recommended_review_status,
            "status": analysis.status,
            "supporting_match_count": len(supporting_matches),
            "settlement_count": len(settlements),
        },
        verifier_status="passed" if has_settlement else "partial",
        items=items,
    )


def _matching_support_settlements(*, transaction: Transaction, supporting_matches: list, ledger_by_id: dict) -> list:
    amount = transaction.debit_amount
    if amount is None:
        return []
    settlements = []
    for match in supporting_matches:
        ledger = ledger_by_id.get(match.document_id)
        if ledger is None:
            continue
        for settlement in build_statement_settlements(ledger):
            if amounts_match(settlement.payment_entry.amount, amount):
                settlements.append(settlement)
    return settlements


def _document_item_role(document: Document | None) -> str:
    if document is None:
        return "support_doc"
    if document.document_type == "invoice":
        return "invoice"
    if document.document_type == "credit_note":
        return "credit_note"
    if document.document_type == "statement":
        return "statement"
    if document.document_type == "receipt":
        return "payment_row"
    return "support_doc"


def _exact_item_role(document: Document | None) -> str:
    base = _document_item_role(document)
    return f"{base}_exact" if base in {"invoice", "credit_note"} else base


def _suggested_item_role(document: Document | None) -> str:
    base = _document_item_role(document)
    return f"{base}_suggested" if base in {"invoice", "credit_note"} else base


def _row_type_for_document(document: Document | None) -> str | None:
    if document is None:
        return None
    if document.document_type in {"invoice", "credit_note", "receipt"}:
        return document.document_type
    return None


def _signed_amount_for_document(document: Document | None, amount: Decimal | None) -> Decimal | None:
    if amount is None:
        return None
    if document and document.document_type == "credit_note":
        return -abs(amount)
    return amount


def _find_document_financial_row_id(*, document: Document | None, row_type: str | None, reference: str | None, amount: Decimal | None):
    if document is None or row_type is None:
        return None
    for row in document.financial_rows or []:
        if row.row_type != row_type:
            continue
        if reference and row.reference != reference:
            continue
        if amount is not None and row.amount != amount:
            continue
        return row.id
    return None


def _find_financial_row_id_for_entry(*, document: Document | None, entry: ParsedLedgerEntry):
    if document is None:
        return None
    return _find_matching_row_id(
        rows=document.financial_rows or [],
        row_type=entry.entry_kind,
        reference=entry.reference,
        clearing_reference=entry.related_reference,
        amount=entry.amount,
        signed_amount=entry.signed_amount,
    )


def _find_matching_row_id(*, rows: list[DocumentFinancialRow], row_type: str, reference: str | None, clearing_reference: str | None, amount: Decimal | None, signed_amount: Decimal | None):
    for row in rows:
        if row.row_type != row_type:
            continue
        if reference and row.reference != reference:
            continue
        if clearing_reference and row.clearing_reference != clearing_reference:
            continue
        if amount is not None and row.amount != amount:
            continue
        if signed_amount is not None and row.signed_amount != signed_amount:
            continue
        return row.id
    return None


def _entry_item_role(entry_kind: str) -> str:
    if entry_kind == LEDGER_ENTRY_INVOICE:
        return "invoice"
    if entry_kind == LEDGER_ENTRY_CREDIT_NOTE:
        return "credit_note"
    if entry_kind == LEDGER_ENTRY_PAYMENT:
        return "payment_row"
    if entry_kind == LEDGER_ENTRY_DISCOUNT:
        return "discount"
    return "support_doc"


def _dedupe_item_specs(items: list[_SuggestionItemSpec]) -> list[_SuggestionItemSpec]:
    deduped: list[_SuggestionItemSpec] = []
    seen: set[tuple] = set()
    for item in items:
        key = (
            item.item_role,
            item.document_id,
            item.financial_row_id,
            item.reference,
            str(item.amount) if item.amount is not None else None,
            str(item.signed_amount) if item.signed_amount is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


async def load_active_reconciliation_suggestions(
    *,
    db: AsyncSession,
    user_id,
    transaction_ids: list,
) -> dict:
    if not transaction_ids:
        return {}

    result = await db.execute(
        select(ReconciliationSuggestion)
        .options(
            selectinload(ReconciliationSuggestion.items).selectinload(ReconciliationSuggestionItem.document),
            selectinload(ReconciliationSuggestion.items).selectinload(ReconciliationSuggestionItem.financial_row),
        )
        .where(
            ReconciliationSuggestion.user_id == user_id,
            ReconciliationSuggestion.transaction_id.in_(transaction_ids),
            ReconciliationSuggestion.status == "suggested",
        )
        .order_by(
            ReconciliationSuggestion.transaction_id.asc(),
            ReconciliationSuggestion.created_at.desc(),
        )
    )
    suggestions = list(result.scalars().all())
    grouped: dict = {}
    for suggestion in suggestions:
        grouped.setdefault(suggestion.transaction_id, []).append(suggestion)
    return grouped


def build_match_lists_from_persisted_suggestions(suggestions: list[ReconciliationSuggestion]) -> tuple[list[PersistedSuggestionMatch], list[PersistedSuggestionMatch], list[PersistedSuggestionMatch]]:
    exact_matches: list[PersistedSuggestionMatch] = []
    suggested_matches: list[PersistedSuggestionMatch] = []
    supporting_matches: list[PersistedSuggestionMatch] = []
    seen: set[tuple] = set()

    for suggestion in suggestions:
        for item in suggestion.items:
            document = item.document
            if document is None:
                continue
            key = (document.id, item.item_role, item.reference, str(item.amount) if item.amount is not None else None)
            if key in seen:
                continue
            seen.add(key)
            match = PersistedSuggestionMatch(
                document_id=document.id,
                document_type=document.document_type,
                supplier=document.supplier,
                reference=item.reference or document.reference,
                document_date=document.document_date,
                amount=item.amount if item.amount is not None else document.amount,
                vat_amount=document.vat_amount,
                score=suggestion.confidence_score,
                reason=suggestion.reason_summary or suggestion.suggestion_type.replace("_", " "),
                storage_state=_document_storage_state(document),
                storage_provider=document.storage_provider,
                storage_bucket=document.storage_bucket,
                storage_key=document.storage_key,
                drive_file_id=document.drive_file_id,
                drive_web_link=document.drive_web_link,
            )
            if item.item_role.endswith("_exact"):
                exact_matches.append(match)
            elif item.item_role.endswith("_suggested"):
                suggested_matches.append(match)
            elif item.item_role in {"statement", "support_doc", "payment_row"}:
                supporting_matches.append(match)

    return exact_matches, suggested_matches, supporting_matches


def select_primary_reconciliation_suggestion(
    suggestions: list[ReconciliationSuggestion] | None,
) -> PersistedPrimarySuggestion | None:
    if not suggestions:
        return None
    primary = min(suggestions, key=_suggestion_rank)
    reason_json = primary.reason_json or {}
    document_count = len({item.document_id for item in primary.items if item.document_id is not None})
    return PersistedPrimarySuggestion(
        suggestion_type=primary.suggestion_type,
        status=primary.status,
        verifier_status=primary.verifier_status,
        confidence_score=primary.confidence_score,
        reason_summary=primary.reason_summary,
        resolution_bucket=reason_json.get("resolution_bucket"),
        recommended_review_status=reason_json.get("recommended_review_status"),
        matcher_status=reason_json.get("status"),
        item_count=len(primary.items),
        document_count=document_count,
        verifier_reasons=list(reason_json.get("verifier_reasons") or []),
    )


def apply_primary_suggestion_to_analysis(*, analysis, primary: PersistedPrimarySuggestion | None) -> None:
    if primary is None:
        return
    if primary.matcher_status:
        analysis.status = primary.matcher_status
    if primary.resolution_bucket:
        analysis.resolution_bucket = primary.resolution_bucket
    if primary.recommended_review_status:
        analysis.recommended_review_status = primary.recommended_review_status
    if primary.reason_summary:
        analysis.resolution_reason = primary.reason_summary
        if not analysis.analysis_note:
            analysis.analysis_note = primary.reason_summary


def _document_storage_state(document: Document) -> str:
    has_r2 = bool(document.storage_provider == "s3" and document.storage_key)
    has_drive = bool(document.drive_file_id)
    if has_r2 and has_drive:
        return "r2_and_drive"
    if has_r2:
        return "r2_only"
    if has_drive:
        return "drive_only"
    return "local_only"


def _apply_deterministic_verifier(
    *,
    transaction: Transaction,
    suggestion: ReconciliationSuggestion,
    document_by_id: dict,
    financial_row_by_id: dict,
) -> None:
    status, reasons, metrics = _evaluate_deterministic_verifier(
        transaction=transaction,
        suggestion=suggestion,
        document_by_id=document_by_id,
        financial_row_by_id=financial_row_by_id,
    )
    suggestion.verifier_status = status
    reason_json = dict(suggestion.reason_json or {})
    reason_json["verifier_reasons"] = reasons
    reason_json["verifier_metrics"] = metrics
    suggestion.reason_json = reason_json


def _evaluate_deterministic_verifier(
    *,
    transaction: Transaction,
    suggestion: ReconciliationSuggestion,
    document_by_id: dict,
    financial_row_by_id: dict,
) -> tuple[str, list[str], dict]:
    transaction_amount = transaction.debit_amount if transaction.debit_amount is not None else transaction.credit_amount
    item_roles = [item.item_role for item in suggestion.items]
    metrics = {
        "item_count": len(suggestion.items),
        "document_count": len({item.document_id for item in suggestion.items if item.document_id is not None}),
    }

    if suggestion.suggestion_type == "rule_resolution":
        return "passed", ["Resolved by an explicit non-document rule."], metrics

    if suggestion.suggestion_type == "direct_invoice_match":
        exact_items = [item for item in suggestion.items if item.item_role.endswith("_exact")]
        suggested_items = [item for item in suggestion.items if item.item_role.endswith("_suggested")]
        signed_total = _sum_item_signed_amounts(
            items=exact_items or suggested_items,
            document_by_id=document_by_id,
            financial_row_by_id=financial_row_by_id,
        )
        metrics["exact_item_count"] = len(exact_items)
        metrics["suggested_item_count"] = len(suggested_items)
        metrics["signed_total"] = str(signed_total) if signed_total is not None else None

        if exact_items and _amount_matches(signed_total, transaction_amount):
            return "passed", ["Exact invoice or credit components sum to the bank amount."], metrics
        if exact_items:
            reasons = ["Exact invoice or credit components were found, but the stored amounts do not fully reconcile to the bank amount."]
            if transaction_amount is None:
                reasons = ["Exact invoice or credit components were found, but the bank amount is missing on the transaction."]
            return "partial", reasons, metrics
        if suggested_items and _any_item_matches_transaction_amount(
            items=suggested_items,
            transaction_amount=transaction_amount,
            document_by_id=document_by_id,
            financial_row_by_id=financial_row_by_id,
        ):
            return "partial", ["A suggested invoice amount matches the bank amount, but it is not yet verified as an exact link."], metrics
        return "failed", ["No exact invoice or credit component could be deterministically verified from the stored rows."], metrics

    if suggestion.suggestion_type == "statement_settlement":
        payment_items = [item for item in suggestion.items if item.item_role == "payment_row"]
        component_items = [
            item
            for item in suggestion.items
            if item.item_role in {"invoice", "credit_note", "discount", "invoice_exact", "credit_note_exact"}
        ]
        metrics["payment_row_count"] = len(payment_items)
        metrics["component_count"] = len(component_items)
        matching_payment_count = sum(
            1
            for item in payment_items
            if _amount_matches(
                _item_amount(
                    item=item,
                    document_by_id=document_by_id,
                    financial_row_by_id=financial_row_by_id,
                    prefer_signed=False,
                ),
                transaction_amount,
            )
        )
        metrics["matching_payment_row_count"] = matching_payment_count
        unbalanced_statement_count = _count_unbalanced_statements(
            suggestion=suggestion,
            document_by_id=document_by_id,
        )
        metrics["unbalanced_statement_count"] = unbalanced_statement_count
        if payment_items and matching_payment_count and component_items:
            if unbalanced_statement_count:
                return (
                    "partial",
                    ["A statement payment row matches the bank amount, but the supporting statement does not internally balance, so its rows cannot be fully trusted yet."],
                    metrics,
                )
            return "passed", ["A stored statement payment row matches the bank amount and has linked invoice or credit components."], metrics
        if payment_items and matching_payment_count:
            return "partial", ["A stored statement payment row matches the bank amount, but the linked invoice or credit components are incomplete."], metrics
        return "partial", ["Supporting statement documents exist, but there is no deterministic payment-to-components settlement group yet."], metrics

    if suggestion.suggestion_type == "supporting_docs_only":
        statement_count = sum(1 for role in item_roles if role == "statement")
        support_doc_count = sum(1 for role in item_roles if role == "support_doc")
        metrics["statement_count"] = statement_count
        metrics["support_doc_count"] = support_doc_count
        if statement_count or support_doc_count:
            return "partial", ["Supporting documents are present, but no deterministic settlement group was verified."], metrics
        return "failed", ["No deterministic supporting-document evidence was stored for this suggestion."], metrics

    return suggestion.verifier_status or "partial", ["Verifier did not recognize this suggestion type."], metrics


def _count_unbalanced_statements(*, suggestion: ReconciliationSuggestion, document_by_id: dict) -> int:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.orm.attributes import NO_VALUE

    count = 0
    seen: set = set()
    for item in suggestion.items:
        document = document_by_id.get(item.document_id) if item.document_id else None
        if document is None or document.id in seen or document.document_type != "statement":
            continue
        seen.add(document.id)
        fact_attr = sa_inspect(document).attrs.financial_fact
        if fact_attr.loaded_value is NO_VALUE:
            continue
        fact = fact_attr.loaded_value
        if fact is not None and fact.arithmetic_status == "unbalanced":
            count += 1
    return count


def _sum_item_signed_amounts(*, items: list[ReconciliationSuggestionItem], document_by_id: dict, financial_row_by_id: dict) -> Decimal | None:
    total = Decimal("0.00")
    found = False
    for item in items:
        amount = _item_amount(
            item=item,
            document_by_id=document_by_id,
            financial_row_by_id=financial_row_by_id,
            prefer_signed=True,
        )
        if amount is None:
            continue
        found = True
        total += amount
    return total if found else None


def _any_item_matches_transaction_amount(*, items: list[ReconciliationSuggestionItem], transaction_amount: Decimal | None, document_by_id: dict, financial_row_by_id: dict) -> bool:
    for item in items:
        if _amount_matches(
            _item_amount(
                item=item,
                document_by_id=document_by_id,
                financial_row_by_id=financial_row_by_id,
                prefer_signed=False,
            ),
            transaction_amount,
        ):
            return True
    return False


def _item_amount(*, item: ReconciliationSuggestionItem, document_by_id: dict, financial_row_by_id: dict, prefer_signed: bool) -> Decimal | None:
    financial_row = financial_row_by_id.get(item.financial_row_id) if item.financial_row_id else None
    if financial_row is not None:
        if prefer_signed and financial_row.signed_amount is not None:
            return financial_row.signed_amount
        if financial_row.amount is not None:
            return financial_row.amount

    if prefer_signed and item.signed_amount is not None:
        return item.signed_amount
    if item.amount is not None:
        return item.amount

    document = document_by_id.get(item.document_id) if item.document_id else None
    if document is not None:
        if prefer_signed and document.document_type == "credit_note" and document.amount is not None:
            return -abs(document.amount)
        return document.amount
    return None


def _amount_matches(left: Decimal | None, right: Decimal | None) -> bool:
    return amounts_match(left, right)


def _suggestion_rank(suggestion: ReconciliationSuggestion) -> tuple[int, int, int]:
    verifier_rank = {
        "passed": 0,
        "partial": 1,
        "failed": 2,
        None: 3,
    }.get(suggestion.verifier_status, 3)
    type_rank = {
        "direct_invoice_match": 0,
        "statement_settlement": 1,
        "supporting_docs_only": 2,
        "rule_resolution": 3,
    }.get(suggestion.suggestion_type, 9)
    score_rank = -int((suggestion.confidence_score or 0.0) * 1000)
    return (verifier_rank, type_rank, score_rank)
