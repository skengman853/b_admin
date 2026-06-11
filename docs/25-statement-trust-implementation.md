# 25 — Statement Trust Implementation (Phases 1–6)

**Date:** 2026-06-10 / 2026-06-11
**Goal:** make statement extraction trustworthy enough that month close becomes fast, explainable, and low-noise — by making statements *prove themselves* arithmetically instead of being trusted on confidence heuristics.

The work strengthens the existing spine without changing the product shape:

```
Document -> Extraction Run -> Financial Facts -> Financial Rows
        -> Reconciliation Suggestion -> Verifier -> Audit/Review UI
```

## Headline result

Share of statements whose extraction is **arithmetically verified** (rows reconcile to the statement's own control totals, or the document is a correctly-recognized non-settlement kind):

| Supplier            | Before  | After     | Notes |
|---------------------|---------|-----------|-------|
| Diageo              | ~1%     | **85.8%** | 323 stmts incl. 93 re-attributed from pub-name suppliers; 138 are sub-account discount trackers (correctly exempt) |
| Connacht Bottlers   | ~5%     | **96.2%** | |
| Heineken            | ~57%    | **93.6%** | |
| BOC                 | ~93%    | **96.6%** | |
| Bulmers             | ~7%     | **63.4%** | Amount Paid column remains its stubborn failure; failures are honestly flagged `unbalanced`, not silently matched |

"Verified" means the maths checks out to the cent: a Diageo statement now proves `opening + invoices − payments = total due` from its own stored rows.

## Phase 1 — Statement arithmetic layer

A statement is a self-verifying document. New service `backend/app/services/statement_arithmetic.py`:

- **Activity mode** (running-balance statements — Diageo ERP, Connacht, Heineken):
  `opening_balance + invoices − credits − payments − discounts = closing_balance`
- **Open-item mode** (statements listing open items with a total due — Bulmers, BOC):
  `invoices − credits − payments − discounts = total_due`, where per-item paid
  amounts net off inside the sum (negative payments = credit applications)
- Verdicts: `balanced` / `unbalanced` (with exact delta) / `insufficient_data` /
  `not_applicable` (sub-account and keg-flow statements, prefix-normalized)
- Tolerance ±0.01 everywhere; all arithmetic computed in Python — model-claimed
  totals are never trusted, only verified
- Row classifier shared by every consumer (`classify_statement_row_kind`):
  invoice / credit_note (incl. REBATE) / payment (incl. `DD-…` direct debits) /
  discount / balance_forward (ignored by arithmetic) / other
- Refinements learned from real documents: brought-forward charges dated before
  `period_start` are excluded (already inside opening balance); `total_due`
  serves as the closing balance when a statement states opening + total due only
  (Diageo layout); mirrored `closing == total_due` open-item statements verify
  when no payment rows are present

**Data model** (migration `b2c3d4e5f6a7`): `document_financial_facts` gains
`opening_balance`, `closing_balance`, `total_due`, `settlement_discount_total`,
`arithmetic_mode`, `arithmetic_status`, `arithmetic_delta`. Control totals no
longer live only inside the AI payload JSON.

**Extraction scoring** (`_apply_statement_quality`): `balanced` floors
confidence at 0.9 and clears statement review reasons; `unbalanced` caps it at
0.55 and adds the `statement_unbalanced` review reason. The old additive
shape-based heuristics remain only for `insufficient_data` cases.

**Bugs fixed in this phase:** forced re-extraction used to *accumulate*
duplicate financial rows (sync deleted by run id, now by document id);
AI-returned currency names ("Euro") crashed Postgres's `String(3)` column —
currency is now normalized to ISO codes by a validator on the result model.

## Phase 2 — Golden corpus + eval harness

`backend/app/eval/extraction_eval.py`, fixtures in
`backend/tests/golden/statements/<family>/<case>/`:

- `document.pdf` — real statement PDF
- `expected.json` — **hand-verified ground truth** (control totals, rows,
  expected arithmetic status); all 26 fixtures verified against the rendered
  PDFs (`"verified": true`)
- `ai_payload.json` — latest production extraction payload, refreshed from the
  DB after re-extractions so replay mode mirrors production

Commands (inside the api container):

```bash
python -m app.eval.extraction_eval seed --supplier Diageo --limit 5   # draft fixtures from DB
python -m app.eval.extraction_eval run                                # replay stored payloads (free, deterministic)
python -m app.eval.extraction_eval run --live-ai                      # real model calls, disk-cached (.eval_cache/)
python -m app.eval.extraction_eval run --write-baseline               # lock in comparison baseline
```

Metrics per parser family: row recall/precision, amount exactness, control-total
accuracy, arithmetic balanced rate — each run prints signed deltas against
`baseline.json`. **Discipline: every prompt/model/input change gets measured
here before merging; every operator-reported extraction bug becomes a fixture
before it is fixed.**

Fixture verification itself caught real bugs: the `sub_account_statement`
exemption only matched one exact string while the model says "sub_account"; a
legitimate closing balance of `0.00` was destroyed by a falsy `or`; REBATE rows
were unclassified.

## Phase 3 — Hybrid text + page-image model input

The root cause of bad statement extraction was input, not model: flattened PDF
text destroys column alignment, and the prompt was asking the model to re-zip
columns it could no longer see.

- `backend/app/services/pdf_images.py` renders pages via poppler `pdftoppm`
  (170 dpi, ≤8 pages; config: `ai_document_extraction_send_page_images`,
  `…_max_image_pages`, `…_image_dpi`)
- The extraction request is now multi-part: page images are the authority for
  table layout; extracted text is the authority for exact digits and references
- `input_kind` (`text_only` / `text_and_images`) recorded on every extraction run
- `pdf_text.py`: pdfplumber page cap raised 2 → 8; missing `pdftotext` now logs
  a warning instead of silently truncating multi-page statements
- Prompt v3 (a `AI_EXTRACTION_PROMPT_VERSION` constant busts the eval cache):
  Diageo column mapping (Billing Doc number is the row reference; Customer
  Reference `D…` values excluded), balance lines never emitted as entries,
  sub-account statements report balances and no entries, statement-of-account
  Amount Paid columns become explicit payment entries

Eval impact (verified corpus, text-only → hybrid): Connacht 1.000 across every
metric and 100% balanced; Diageo recall/precision 0.43–0.95 → **1.000** with all
main ERP statements balanced to the cent; statement-of-account 20% → 80%
balanced. Scanned statements with no text layer work for free.

## Phase 4 — Bounded repair pass

When a statement extraction fails its own arithmetic, the pipeline makes
**exactly one** retry whose prompt includes the verification mode and the exact
delta ("rows differ from stated totals by 3,387.37; an Amount Paid column may
have been skipped…"). Whichever attempt balances is kept.

- `document_extraction._maybe_repair_statement_extraction`, config-gated by
  `ai_document_extraction_repair_enabled`
- Fully audited: run `source_kind` becomes `ai_repair`; run payload records
  `repair_attempted`, `repair_used`, and the rejected `first_attempt_payload`
- A statement that fails twice goes to the operator with a precise reason —
  that is the product working, not failing

**Verifier trust-link:** a `statement_settlement` suggestion whose supporting
statement has `arithmetic_status = 'unbalanced'` is capped at `partial` — a
settlement built on rows that don't add up can never present as `passed`.

## Phase 5 — Read-path unification

Persisted facts/rows are the source of truth at read time. `build_document_ledger`
now has an explicit three-state contract:

- `allow_parse_fallback=True` — writers (extraction sync) and transient
  documents (eval) parse silently; this is where rows get *created*
- `False` — strict: no persisted state, no ledger
- default — parse, but **log a drift warning** distinguishing "call site forgot
  to eager-load `financial_fact`/`financial_rows`" from "extracted document was
  never synced"

Strict-by-default was tried and deliberately reverted: matching not-yet-extracted
statements as weak context is an intentional product behavior ("regex as
fallback/gap-filling"). The dangerous drift class — re-parsing a statement whose
stored rows exist but weren't loaded — is exactly what the warning catches. All
production matcher call sites were audited and eager-load correctly.

## Phase 6 — Discount-aware settlements + one tolerance rule

- Discount rows participate in settlement grouping: the existing subset-sum now
  resolves `invoices − discount = payment` with no supplier-specific logic
  (prompt-payment terms at Diageo/Heineken are the motivating case; the
  mechanism is a general row type)
- The verifier counts `discount` item roles as settlement components
- `statement_arithmetic.amounts_match` (±0.01) is the single amount-comparison
  rule, replacing exact `Decimal ==` in settlement subset-sums,
  settlement-to-bank matching, direct entry matching, and four sites in
  `transaction_reconciliation`

Note: live data currently contains no discount rows (Diageo prints its discount
column as info-only and the prompt keeps it out of entries by design); this is
plumbing for suppliers that line-item discounts.

## Supplier re-attribution (parallel fix)

93 statements had the operator's own pub names ("Careys Bar", "Canal Turn")
recorded as supplier. An `is_operator_entity()` registry in
`supplier_profiles.py` now blocks pub names at every attribution point, and
`scripts/reattribute_operator_supplier_documents.py` re-attributed the affected
documents (to Diageo). 5 scanned rebate credit memos without extracted text
remain pending re-extraction.

## Operational notes

- **Re-extraction:** `backend/scripts/reextract_statements.py [worker_index worker_count]`
  — resumable (skips already-extracted, `reviewed`, `split`), partition-safe for
  parallel workers. All 703 statements were re-extracted with hybrid input;
  a targeted repair sweep then re-ran the ~105 remaining unverified ones.
- **Backfill (no AI cost):** `POST /documents/backfill-financial-state`
  re-syncs facts/rows/arithmetic from stored extractions.
- **Monitoring drift:** grep api logs for the `page-time parse` warnings from
  `document_ledger`; any occurrence is a bug (missing eager-load or unsynced doc).
- **Test suite:** 17 failures pre-date this work (including a
  float-vs-Query-default TypeError at `api/documents.py:187`); every phase was
  verified to add zero new failures against that baseline.

## Known gaps / next candidates

1. **Bulmers Amount Paid column** (~15 statements): the model skips it on about
   half of extractions even with the repair hint. Options: more Bulmers
   fixtures + prompt iteration, or a stronger model used only for repair
   attempts. All failures are honestly flagged `unbalanced`.
2. **Remaining `insufficient_data`** (~80 docs incl. older re-attributed Diageo
   docs and 5 scanned credit memos): mostly genuinely sparse documents; a
   re-extraction pass after the supplier re-attribution would shrink this.
3. **Operator surface:** a small balanced/unbalanced badge on statement evidence
   in `/month-audit` and `/review` (the data is on `document_financial_facts`;
   deliberately deferred to keep UI churn out of this changeset).
4. **CI:** wire `extraction_eval run` (replay mode, free and deterministic —
   confirmed to match the live baseline exactly) into CI as a regression gate.
