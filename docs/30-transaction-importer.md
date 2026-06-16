# 30 — The Transaction Importer (bank CSV → transaction rows)

This is the design for the **right half** of the reconciliation system: getting
the bank's money movements into the database so they can be matched against the
documents (invoices / statements / credit notes) produced by the pipeline in
[doc 29](29-pipeline-stages.md).

```
   DOCUMENTS (what you were billed)            TRANSACTIONS (money that moved)
   email → invoices, statements, CNs           bank → debits / credits
            │                                            │
            └──────────────► RECONCILIATION ◄────────────┘
                       "what document explains this payment?"
```

Doc 29 builds the left half. This doc builds the right half. The matching engine
that joins them is a separate, later doc.

## It's an importer, not an extractor

The document side is genuinely hard — AI reading a messy supplier PDF. The
transaction side is **not that**. A bank CSV is already structured: rows and
columns of date / description / debit / credit. The job is **parse, normalise,
store** — deterministic, no AI.

> **What this replaces.** Today the bank side parses **AIB PDF statements** by
> pixel column position (`bank_statement_parser.py` — `_DEBIT_MIN_X = 250.0`,
> AIB footer markers, pdfplumber). That is fragile and bank-specific. Moving to
> **CSV** removes the coordinate-guessing entirely: the bank gives clean columns,
> we map them once. CSV also opens in Excel, so it's the same thing the
> bookkeeper would eyeball.

## Same core principle: DB is truth

Identical to doc 29. The **`transactions` table on Railway Postgres** is the
source of truth. The original CSV is kept in **Cloudflare R2** for audit, and
each row's original values are kept in the `raw_row_json` column — but the truth
the system reasons over is the parsed rows, not the file.

## The lifecycle

A transaction is one row that climbs a short ladder, mirroring the document side:

```
              [1. Import]              [2. Categorise]
  (bank CSV) ───────────▶ imported ──────────────▶ categorised
                          raw rows in,             VAT rate + resale/
                          nothing classified       non-resale assigned
```

| Stage         | Meaning                                          | Represented in DB by                       |
|---------------|--------------------------------------------------|--------------------------------------------|
| `imported`    | Clean rows parsed from the CSV, nothing decided  | row exists; `category` null                |
| `categorised` | VAT treatment assigned (resale / non-resale / rates) | `category` set; VAT split columns filled |

Reconciliation (matching a transaction to its document) is **not a stage of the
transaction** — it's a separate cross-cutting engine that reads both sides. The
existing `review_status` column tracks that, and it's covered in the matching
doc, not here.

> **Stage column:** like doc 29, add one explicit `stage` column rather than
> inferring it. The `transactions` table already has `category` /
> `category_confirmed` / `review_status`, but those describe *categorisation* and
> *matching*, not pipeline position — keep `stage` separate and explicit.

## Stage 1 — Import (button: "Upload bank statement")

**Drop a CSV in, get clean transaction rows out. No categorising, no matching.**

- Operator uploads the CSV (a file picker / drag-and-drop, like the extraction
  tester page).
- Store the raw CSV in R2 for audit.
- Parse each row and **map the bank's columns** to the canonical fields:

  | Canonical field      | From the CSV                                   |
  |----------------------|------------------------------------------------|
  | `transaction_date`   | the date column                                |
  | `description1/2`     | the narrative / details column(s)              |
  | `debit_amount`       | money out (or the negative side of a signed amount) |
  | `credit_amount`      | money in (or the positive side)                |
  | `raw_row_json`       | the whole original row, verbatim, for audit    |

- Write one `transactions` row per CSV line at stage `imported`,
  `source_type = 'bank_statement'`.

The column mapping is the **only bank-specific part**. We define it once for the
bank's CSV layout; if the layout changes or a second bank is added, that's a new
mapping, not new parsing code.

### Dedup

The table already has a unique index on
`(user_id, source_file, source_sheet, row_number)`. For CSV, `source_file` is the
filename and `row_number` is the line number — so re-uploading the same file
won't create duplicates. A `replace_existing` option (already in the import API)
lets you re-import a corrected file cleanly.

## Stage 2 — Categorise (button: "Categorise")

**For each imported transaction, assign its VAT treatment.**

- Run the existing categorisation logic (`vat_categorisation.py`): decide the
  category and the resale / non-resale / rate split
  (`resale_23_amount`, `non_resale_13_5_amount`, …).
- Set `category`, fill the VAT split columns, advance stage to `categorised`.
- Low-confidence guesses stay flagged for the operator to confirm
  (`category_confirmed = false`), same inline-fix idea as unknown suppliers in
  doc 29 — and the choice is remembered as a rule (`transaction_rules`) so similar
  descriptions auto-categorise next time.

This stage is kept separate from import on purpose: import should be dumb, fast,
and trustworthy; categorisation is the judgement step you inspect.

## Storage model

| Thing                         | Where it lives                          |
|-------------------------------|-----------------------------------------|
| Transaction rows + stage      | Railway Postgres `transactions` table   |
| VAT split / category          | columns on the same row                 |
| Original CSV file             | Cloudflare R2 (audit copy)              |
| Per-row original values       | `raw_row_json` column                   |

Same destinations as doc 29: **Railway Postgres (truth) + Cloudflare R2 (the
uploaded file)**.

## What changes from today

1. **Bank input becomes CSV**, replacing fragile AIB-PDF coordinate parsing.
2. **Import splits from categorise** — two buttons, each inspectable.
3. (Recommended) **add a `stage` column** to make pipeline position explicit.
4. **Matching stays out of scope here** — it's the engine that reads both halves,
   designed in its own doc.

## Decisions locked

- **Source**: bank statement **file upload** (not email, not bank API).
- **Format**: **CSV** (provisional — confirm the actual bank export; if it turns
  out PDF-only, that's a harder extraction job more like doc 29).
- **Truth store**: Railway Postgres `transactions`; original CSV archived in R2.
- **Scope**: **import raw rows first** (stage 1); categorisation is a separate
  stage 2 — not bundled into import.

## Still open (decide next)

- **Exact CSV columns**: confirm the bank's real column names/order at home, then
  pin the mapping table above.
- **Signed amount vs split columns**: does the bank give one signed `amount`
  column, or separate debit/credit columns? Changes the mapping.
- **The matching engine**: the next doc — how an `imported`/`categorised`
  transaction gets linked to the document that explains it.
