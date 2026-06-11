"""Golden-corpus evaluation harness for statement extraction quality.

Fixtures live in ``tests/golden/statements/<family>/<case>/``:

- ``document.pdf``       the real (redacted) statement PDF
- ``expected.json``      hand-verified ground truth (control totals + rows)
- ``ai_payload.json``    optional stored AI payload for replay mode (no API cost)

Commands (run inside the api container)::

    python -m app.eval.extraction_eval run [--family diageo_erp_statement] [--live-ai] [--write-baseline]
    python -m app.eval.extraction_eval seed --supplier Diageo --limit 5

``run`` replays each fixture through the real extraction path (text -> AI ->
merge -> ledger -> arithmetic) and scores it against ``expected.json``.
Without ``--live-ai`` it uses ``ai_payload.json`` so runs are free and
deterministic. ``seed`` drafts fixtures from already-extracted documents in
the database; drafts have ``"verified": false`` until a human confirms them.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

GOLDEN_ROOT = Path(__file__).resolve().parents[2] / "tests" / "golden" / "statements"
CACHE_ROOT = Path(__file__).resolve().parents[2] / ".eval_cache"
BASELINE_PATH = GOLDEN_ROOT / "baseline.json"
RESULTS_PATH = GOLDEN_ROOT / "results.json"

TRACKED_CONTROL_TOTALS = ("opening_balance", "closing_balance", "total_due", "settlement_discount_total")


def _decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _normalize_reference(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum()).lstrip("0")


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


def discover_cases(family: str | None = None) -> list[Path]:
    if not GOLDEN_ROOT.exists():
        return []
    families = sorted(p for p in GOLDEN_ROOT.iterdir() if p.is_dir())
    if family:
        families = [p for p in families if p.name == family]
    return [case for fam in families for case in sorted(fam.iterdir()) if (case / "expected.json").exists()]


async def run_case(case_dir: Path, *, live_ai: bool) -> dict:
    from app.models import Document
    from app.services.ai_document_extraction import merge_ai_extraction
    from app.services.document_extraction import _build_statement_ai_primary_fields
    from app.services.document_extraction_rules import build_extraction_fields
    from app.services.document_ledger import build_document_ledger
    from app.services.pdf_text import extract_pdf_text
    from app.services.statement_arithmetic import ArithmeticRow, verify_statement_arithmetic

    expected = json.loads((case_dir / "expected.json").read_text())
    pdf_path = case_dir / "document.pdf"
    pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
    extracted_text = extract_pdf_text(pdf_bytes) if pdf_bytes else ""

    document = Document(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        gmail_message_id=f"eval-{case_dir.name}",
        attachment_index=0,
        derivation_index=0,
        attachment_name=expected.get("attachment_name") or pdf_path.name,
        source_email_subject=expected.get("source_email_subject") or "",
        supplier=expected.get("supplier") or "Other",
        document_type=expected.get("document_type") or "statement",
        extracted_text=extracted_text,
    )

    ai_result = await _resolve_ai_result(
        case_dir=case_dir,
        document=document,
        extracted_text=extracted_text,
        pdf_bytes=pdf_bytes,
        live_ai=live_ai,
    )
    if ai_result is not None:
        fields = merge_ai_extraction(
            document=document,
            extraction_fields=_build_statement_ai_primary_fields(
                document=document,
                extracted_text=extracted_text,
                ai_result=ai_result,
            ),
            ai_result=ai_result,
        )
    else:
        fields = build_extraction_fields(
            extracted_text=extracted_text,
            supplier=document.supplier,
            document_type=document.document_type,
            subject=document.source_email_subject or "",
            attachment_name=document.attachment_name,
        )
    for field, value in fields.items():
        if hasattr(document, field):
            setattr(document, field, value)

    ledger = build_document_ledger(document, allow_parse_fallback=True)
    arithmetic = verify_statement_arithmetic(
        rows=[
            ArithmeticRow(kind=entry.entry_kind, amount=entry.amount, event_date=entry.event_date)
            for entry in (ledger.entries if ledger is not None else [])
        ],
        opening_balance=ledger.opening_balance if ledger else None,
        closing_balance=ledger.closing_balance if ledger else None,
        total_due=ledger.total_due if ledger else None,
        settlement_discount_total=ledger.settlement_discount_total if ledger else None,
        statement_kind=ledger.statement_kind if ledger else None,
        period_start=ledger.period_start if ledger else None,
    )

    return score_case(
        case_dir=case_dir,
        expected=expected,
        ledger=ledger,
        arithmetic=arithmetic,
        used_ai=ai_result is not None,
    )


async def _resolve_ai_result(*, case_dir: Path, document, extracted_text: str, pdf_bytes: bytes, live_ai: bool):
    from app.config import settings
    from app.services.ai_document_extraction import (
        AI_EXTRACTION_PROMPT_VERSION,
        AIDocumentExtractionResult,
        extract_document_with_ai,
    )
    from app.services.pdf_images import render_pdf_page_images

    if live_ai:
        page_images: list[bytes] = []
        if settings.ai_document_extraction_send_page_images and pdf_bytes:
            page_images = render_pdf_page_images(
                pdf_bytes,
                max_pages=settings.ai_document_extraction_max_image_pages,
                dpi=settings.ai_document_extraction_image_dpi,
            )
        input_kind = "text_and_images" if page_images else "text_only"
        cache_key = hashlib.sha256(
            f"{settings.ai_document_extraction_model}\n{AI_EXTRACTION_PROMPT_VERSION}\n"
            f"{input_kind}\n{document.supplier}\n{extracted_text}".encode()
        ).hexdigest()
        cache_path = CACHE_ROOT / f"{cache_key}.json"
        if cache_path.exists():
            return AIDocumentExtractionResult.model_validate(json.loads(cache_path.read_text()))
        ai_result = await extract_document_with_ai(
            document=document,
            extracted_text=extracted_text,
            page_images=page_images,
        )
        if ai_result is not None:
            CACHE_ROOT.mkdir(exist_ok=True)
            cache_path.write_text(json.dumps(ai_result.model_dump(mode="json")))
        return ai_result

    payload_path = case_dir / "ai_payload.json"
    if payload_path.exists():
        return AIDocumentExtractionResult.model_validate(json.loads(payload_path.read_text()))
    return None


def score_case(*, case_dir: Path, expected: dict, ledger, arithmetic, used_ai: bool) -> dict:
    expected_rows = expected.get("rows") or []
    extracted_rows = [
        {
            "row_type": entry.entry_kind,
            "reference": entry.reference,
            "event_date": entry.event_date.isoformat() if entry.event_date else None,
            "amount": str(entry.amount) if entry.amount is not None else None,
        }
        for entry in (ledger.entries if ledger is not None else [])
    ]

    matched, amount_exact = _match_rows(expected_rows, extracted_rows)

    expected_totals = expected.get("control_totals") or {}
    totals_expected = 0
    totals_correct = 0
    for name in TRACKED_CONTROL_TOTALS:
        expected_value = _decimal(expected_totals.get(name))
        if expected_value is None:
            continue
        totals_expected += 1
        actual = getattr(ledger, name, None) if ledger is not None else None
        if actual is not None and abs(actual - expected_value) <= Decimal("0.01"):
            totals_correct += 1

    expected_status = expected.get("expected_arithmetic_status")
    return {
        "case": f"{case_dir.parent.name}/{case_dir.name}",
        "family": case_dir.parent.name,
        "verified": bool(expected.get("verified")),
        "used_ai": used_ai,
        "expected_row_count": len(expected_rows),
        "extracted_row_count": len(extracted_rows),
        "matched_row_count": matched,
        "row_recall": round(matched / len(expected_rows), 3) if expected_rows else None,
        "row_precision": round(matched / len(extracted_rows), 3) if extracted_rows else None,
        "amount_exact_rate": round(amount_exact / matched, 3) if matched else None,
        "totals_expected": totals_expected,
        "totals_correct": totals_correct,
        "arithmetic_mode": arithmetic.mode,
        "arithmetic_status": arithmetic.status,
        "arithmetic_delta": str(arithmetic.delta) if arithmetic.delta is not None else None,
        "arithmetic_status_matches_expected": (
            arithmetic.status == expected_status if expected_status else None
        ),
    }


def _match_rows(expected_rows: list[dict], extracted_rows: list[dict]) -> tuple[int, int]:
    remaining = list(extracted_rows)
    matched = 0
    amount_exact = 0
    for expected_row in expected_rows:
        hit = _find_row(expected_row, remaining, require_amount=True)
        if hit is None:
            hit = _find_row(expected_row, remaining, require_amount=False)
        if hit is None:
            continue
        remaining.remove(hit)
        matched += 1
        if expected_row.get("amount") is not None and _decimal(hit.get("amount")) == _decimal(expected_row.get("amount")):
            amount_exact += 1
    return matched, amount_exact


def _find_row(expected_row: dict, candidates: list[dict], *, require_amount: bool) -> dict | None:
    expected_ref = _normalize_reference(expected_row.get("reference"))
    expected_amount = _decimal(expected_row.get("amount"))
    expected_type = expected_row.get("row_type")
    for candidate in candidates:
        if expected_type and candidate.get("row_type") and candidate["row_type"] != expected_type:
            continue
        if expected_ref and _normalize_reference(candidate.get("reference")) != expected_ref:
            continue
        if not expected_ref and candidate.get("reference"):
            continue
        if require_amount and expected_amount is not None and _decimal(candidate.get("amount")) != expected_amount:
            continue
        return candidate
    return None


def aggregate_results(case_results: list[dict]) -> dict:
    families: dict[str, dict] = {}
    for result in case_results:
        bucket = families.setdefault(
            result["family"],
            {
                "cases": 0,
                "verified_cases": 0,
                "row_recall_sum": 0.0,
                "row_recall_n": 0,
                "row_precision_sum": 0.0,
                "row_precision_n": 0,
                "amount_exact_sum": 0.0,
                "amount_exact_n": 0,
                "totals_expected": 0,
                "totals_correct": 0,
                "balanced": 0,
                "unbalanced": 0,
                "insufficient_data": 0,
                "not_applicable": 0,
            },
        )
        bucket["cases"] += 1
        bucket["verified_cases"] += 1 if result["verified"] else 0
        for metric, total_key, count_key in (
            ("row_recall", "row_recall_sum", "row_recall_n"),
            ("row_precision", "row_precision_sum", "row_precision_n"),
            ("amount_exact_rate", "amount_exact_sum", "amount_exact_n"),
        ):
            if result[metric] is not None:
                bucket[total_key] += result[metric]
                bucket[count_key] += 1
        bucket["totals_expected"] += result["totals_expected"]
        bucket["totals_correct"] += result["totals_correct"]
        bucket[result["arithmetic_status"]] = bucket.get(result["arithmetic_status"], 0) + 1

    summary = {}
    for family, bucket in sorted(families.items()):
        summary[family] = {
            "cases": bucket["cases"],
            "verified_cases": bucket["verified_cases"],
            "row_recall": round(bucket["row_recall_sum"] / bucket["row_recall_n"], 3) if bucket["row_recall_n"] else None,
            "row_precision": round(bucket["row_precision_sum"] / bucket["row_precision_n"], 3) if bucket["row_precision_n"] else None,
            "amount_exact_rate": round(bucket["amount_exact_sum"] / bucket["amount_exact_n"], 3) if bucket["amount_exact_n"] else None,
            "control_totals_accuracy": (
                round(bucket["totals_correct"] / bucket["totals_expected"], 3) if bucket["totals_expected"] else None
            ),
            "arithmetic_balanced_rate": round(bucket["balanced"] / bucket["cases"], 3),
            "arithmetic_statuses": {
                status: bucket[status]
                for status in ("balanced", "unbalanced", "insufficient_data", "not_applicable")
                if bucket[status]
            },
        }
    return summary


def print_summary(summary: dict, baseline: dict | None) -> None:
    headers = ("family", "cases", "recall", "precision", "amt_exact", "totals", "balanced")
    print(f"{headers[0]:<28} {headers[1]:>5} {headers[2]:>7} {headers[3]:>9} {headers[4]:>9} {headers[5]:>7} {headers[6]:>9}")
    for family, metrics in summary.items():
        deltas = ""
        if baseline and family in baseline:
            previous = baseline[family].get("arithmetic_balanced_rate")
            current = metrics["arithmetic_balanced_rate"]
            if previous is not None and current is not None:
                deltas = f"  (balanced {current - previous:+.3f} vs baseline)"
        print(
            f"{family:<28} {metrics['cases']:>5} "
            f"{_fmt(metrics['row_recall']):>7} {_fmt(metrics['row_precision']):>9} "
            f"{_fmt(metrics['amount_exact_rate']):>9} {_fmt(metrics['control_totals_accuracy']):>7} "
            f"{_fmt(metrics['arithmetic_balanced_rate']):>9}{deltas}"
        )


def _fmt(value) -> str:
    return "-" if value is None else f"{value:.3f}"


async def command_run(args) -> int:
    cases = discover_cases(args.family)
    if not cases:
        print(f"No fixture cases found under {GOLDEN_ROOT}" + (f" for family {args.family}" if args.family else ""))
        return 1

    case_results = []
    for case_dir in cases:
        result = await run_case(case_dir, live_ai=args.live_ai)
        case_results.append(result)

    summary = aggregate_results(case_results)
    baseline = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else None
    print_summary(summary, baseline)

    RESULTS_PATH.write_text(json.dumps({"summary": summary, "cases": case_results}, indent=2))
    print(f"\nDetailed results written to {RESULTS_PATH}")
    if args.write_baseline:
        BASELINE_PATH.write_text(json.dumps(summary, indent=2))
        print(f"Baseline written to {BASELINE_PATH}")
    return 0


# ---------------------------------------------------------------------------
# seed command
# ---------------------------------------------------------------------------


async def command_seed(args) -> int:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db import async_session
    from app.models import Document
    from app.services.object_storage import ensure_local_document_file
    from app.services.supplier_profiles import detect_statement_parser_family

    async with async_session() as session:
        query = (
            select(Document)
            .options(selectinload(Document.financial_fact), selectinload(Document.financial_rows))
            .where(
                Document.document_type == "statement",
                Document.derivation_index == 0,
                Document.ai_extraction_payload.is_not(None),
            )
            .order_by(Document.created_at.desc())
            .limit(args.limit)
        )
        if args.supplier:
            query = query.where(Document.supplier == args.supplier)
        if args.document_ids:
            query = query.where(Document.id.in_(args.document_ids))
        documents = (await session.execute(query)).scalars().all()

    if not documents:
        print("No matching extracted statements found to seed from.")
        return 1

    seeded = 0
    for document in documents:
        family = detect_statement_parser_family(
            supplier=document.supplier,
            text=document.extracted_text or "",
        ) or "generic_statement"
        case_dir = GOLDEN_ROOT / family / f"{document.id.hex[:12]}"
        if (case_dir / "expected.json").exists():
            continue
        try:
            pdf_path = ensure_local_document_file(document)
        except FileNotFoundError:
            print(f"skip {document.id}: pdf missing")
            continue
        case_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf_path, case_dir / "document.pdf")
        (case_dir / "ai_payload.json").write_text(json.dumps(document.ai_extraction_payload, indent=2))
        (case_dir / "expected.json").write_text(json.dumps(_draft_expected(document), indent=2))
        seeded += 1
        print(f"seeded {case_dir.relative_to(GOLDEN_ROOT.parents[1])}")

    print(f"\nSeeded {seeded} draft fixture(s). Review each expected.json against the PDF, correct it, then set \"verified\": true.")
    return 0


def _draft_expected(document) -> dict:
    fact = document.financial_fact
    rows = sorted(document.financial_rows or [], key=lambda row: row.row_index)
    return {
        "supplier": document.supplier,
        "document_type": document.document_type,
        "attachment_name": document.attachment_name,
        "source_email_subject": document.source_email_subject or "",
        "verified": False,
        "statement_kind": fact.statement_kind if fact else None,
        "control_totals": {
            name: str(getattr(fact, name)) if fact and getattr(fact, name) is not None else None
            for name in TRACKED_CONTROL_TOTALS
        },
        "expected_arithmetic_status": fact.arithmetic_status if fact else None,
        "rows": [
            {
                "row_type": row.row_type,
                "reference": row.reference,
                "event_date": row.event_date.isoformat() if row.event_date else None,
                "amount": str(row.amount) if row.amount is not None else None,
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="score golden fixtures through the extraction pipeline")
    run_parser.add_argument("--family", help="limit to one parser family directory")
    run_parser.add_argument("--live-ai", action="store_true", help="call the AI model (cached) instead of replaying stored payloads")
    run_parser.add_argument("--write-baseline", action="store_true", help="store this run's summary as the comparison baseline")

    seed_parser = subparsers.add_parser("seed", help="draft fixtures from extracted statements in the database")
    seed_parser.add_argument("--supplier", help="exact supplier name to seed from")
    seed_parser.add_argument("--limit", type=int, default=5)
    seed_parser.add_argument("--document-ids", nargs="*", help="specific document ids to seed")

    args = parser.parse_args()
    if args.command == "run":
        return asyncio.run(command_run(args))
    return asyncio.run(command_seed(args))


if __name__ == "__main__":
    raise SystemExit(main())
