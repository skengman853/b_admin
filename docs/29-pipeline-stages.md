# 29 — The Staged Ingestion Pipeline (capture → sort → extract)

This is the design for how documents move through the system, decided in the
"put it on paper" session. It supersedes the all-at-once scan described in older
docs. The goal is a **staged conveyor belt**: each stage is a button, each stage
is independently runnable and inspectable, and you can stop and look at the
result after any stage before moving on.

## Core principle: the database is the truth, folders are a view

There is **one source of truth: the `documents` table** (plus its child tables
for extracted data). "Folders" — `Unsorted`, `Diageo/Invoices`, etc. — are not
real directories that we shuffle files between. They are a **view produced by
querying the DB**:

- "Unsorted pile" = rows where supplier is still unknown.
- "Diageo / Unsorted" = rows where `supplier = 'Diageo'` but type is unknown.
- "Diageo / Invoices" = rows where `supplier = 'Diageo'` AND `document_type = 'invoice'`.

**Moving a document "into a folder" = updating a column on its row.** Nothing
moves on disk. This is what keeps the system simple: a sort is a cheap, reversible
DB update, not a fragile file move across local disk + R2 + Drive.

The **PDF bytes** live in exactly one blob store (R2 *or* local — see Storage).
The **extracted data** lives in DB child tables. Any "folder tree" the operator
sees is rendered on demand from those rows.

## The document lifecycle

Each document row carries a **stage**. The three buttons advance it:

```
                 [1. Capture]          [2. Sort]              [3. Extract]
  (Gmail inbox) ────────────▶ captured ────────▶ supplier_sorted ────────▶ extracted
                              every PDF,          supplier known,           type known,
                              no filtering        type unknown              data pulled
```

| Stage             | Meaning                                              | Represented in DB by                                    |
|-------------------|------------------------------------------------------|---------------------------------------------------------|
| `captured`        | PDF pulled from email, nothing decided yet           | row exists; `supplier='Other'`, `document_type='unknown'` |
| `supplier_sorted` | We know who it's from, not what it is                | `supplier` set to real name; `document_type='unknown'`  |
| `extracted`       | Typed (invoice/statement/credit note) + data pulled  | `document_type` set; financial facts/rows populated     |

> **Decided:** `documents` gets one explicit `stage` column
> (`captured` | `supplier_sorted` | `extracted`). The buttons read and advance
> it directly, so each stage's query is trivial ("give me everything in
> `captured`"). The existing `extraction_status` field stays separate — it tracks
> extraction success/failure, not pipeline position. This is a small Alembic
> migration: add the column, default existing rows to `extracted` (they've
> already been through the old all-at-once flow).

## Stage 1 — Capture (button: "Run")

**Take every email with a PDF attachment. No keyword filtering.**

This is the big change from today. The current code (`email_filter.py`) drops
emails from unknown senders unless the subject/filename contains words like
`invoice`/`statement`. That can silently lose real documents. The new rule:

> If the email has a PDF attachment, capture it.

- Gmail query stays attachment-based: `in:inbox has:attachment filename:pdf`.
- For each new message, download each PDF.
- Write one `documents` row per PDF at stage `captured`, `supplier='Other'`,
  `document_type='unknown'`.
- Store the PDF bytes in the blob store.
- Record the Gmail message id so it is never re-captured (dedup).

The "Unsorted pile" the operator sees is simply: `WHERE stage = 'captured'`.

What is *removed* from this stage vs. today: no supplier detection, no type
classification, no regex metadata, no file move. Capture is dumb and fast on
purpose — it just gets the bytes safely into the system.

Built from: `gmail_client.py` (fetch), a trimmed `document_pipeline.py` (write
rows only), `object_storage.py` (blob store). `email_filter.py`'s keyword gate is
retired.

## Stage 2 — Sort (button: "Sort")

**For each captured document, decide the supplier. Nothing else.**

- Read the PDF (text + sender) and determine the supplier (`detect_supplier`).
- Set `supplier` on the row; advance stage to `supplier_sorted`.
- If the supplier can't be determined confidently, leave it in a
  **"needs a human" bucket** (supplier stays `Other`, flagged) rather than
  guessing — the operator assigns it.

After this stage the view shows `<Supplier>/Unsorted` for each supplier:
`WHERE supplier = ? AND stage = 'supplier_sorted'`.

Built from: `supplier_rules.py` / `supplier_profiles.py` (`detect_supplier`).

## Stage 3 — Sort Supplier (button: "Sort Supplier", per supplier)

**Deep-dive each of a supplier's unsorted docs: classify the type, pull the
numbers, store the data.**

This is where the real extraction happens — the expensive, AI-backed step.

- Classify document type: invoice / statement / credit note / receipt
  (`document_classifier.py`).
- Run extraction (`ai_document_extraction.py` → `document_extraction.py`):
  pull amount, VAT, date, reference; for statements, pull every row + control
  totals and run the arithmetic check (`statement_arithmetic.py`).
- Persist the structured result to the child tables: `document_extraction_runs`,
  `document_financial_facts`, `document_financial_rows`.
- Set `document_type`; advance stage to `extracted`.

Running it **per supplier** (not globally) is deliberate: it keeps each run
small and inspectable, and lets you tune/debug one supplier's statement format
(Diageo, Heineken, …) without reprocessing everything.

After this stage the view shows `<Supplier>/Invoices`, `<Supplier>/Statements`,
etc.: `WHERE supplier = ? AND document_type = ?`.

## The "Extracted data" mirror

You described a second tree that mirrors the PDF tree but holds the *extracted
data* instead of the PDF. In the DB-is-truth model this is **not a second store**
— it already exists as the financial child tables. If you want to *browse* it as
files (e.g. to hand to the bookkeeper or eyeball a supplier), it's an **export**:
generate `Extracted/<Supplier>/<Type>/<ref>.json` on demand from the rows. Real
artifact, generated when asked, never maintained in parallel.

## Storage model

| Thing                | Where it lives                              |
|----------------------|---------------------------------------------|
| Document metadata + stage | **Railway Postgres** `documents` row   |
| Extracted numbers/rows    | **Railway Postgres** `document_financial_*` tables |
| The PDF bytes        | **Cloudflare R2** (the single home for PDFs) |
| Folder trees         | Views — SQL queries, not directories        |
| `Extracted/*.json`   | Optional on-demand export                   |

This collapses today's four overlapping stores (local folders, DB, R2, Drive)
to **Railway Postgres (truth) + Cloudflare R2 (PDF bytes)**. Google Drive and the
on-disk folder tree are dropped. Local disk may still be used as a transient
scratch area during capture (download → push to R2 → delete local), but it is
never a store of record.

### Pointing the app at Railway Postgres

The DB connection is just the `database_url` setting (`app/config.py`, read from
env) — no code change, only configuration. Two gotchas when wiring Railway:

1. **Driver prefix.** Railway hands you `postgresql://user:pass@host:port/db`.
   This app uses asyncpg, so the scheme must be rewritten to
   `postgresql+asyncpg://user:pass@host:port/db`.
2. **SSL is required.** Append `?ssl=require` to the URL (asyncpg honours it),
   otherwise the connection is refused.
3. **Which host:** use Railway's **public** connection string (the proxy host)
   while the app runs locally; switch to the **internal** `*.railway.internal`
   host only if/when the app itself is deployed on Railway.

Set it as `database_url` in `.env` (the migration step `alembic upgrade head`
then runs against Railway).

## What changes from today

1. **Capture stops filtering** — every PDF is kept; sorting happens later.
2. **The single scan splits into three buttons** — capture / sort / sort-supplier.
3. **Sorting becomes a DB update**, not a file move; no physical folder tree.
4. **Storage collapses** to DB + one blob store; Drive + local folders retired.
5. (Recommended) **add a `stage` column** to make pipeline position explicit.

## Decisions locked

- **Truth store**: Railway-managed Postgres holds `documents` + the financial
  child tables. Connect via `database_url` (asyncpg prefix + `?ssl=require`).
- **Blob store**: Cloudflare R2 is the single home for PDF bytes.
- **`stage` column**: explicit `stage` column on `documents`
  (`captured` | `supplier_sorted` | `extracted`).
- **Stages don't auto-advance.** Each button stops at its stage so the result
  can be inspected before moving on. A combined "do everything" button can be
  added later, once each stage is trusted.
- **Unknown suppliers are fixed inline.** A doc Sort can't identify stays in the
  Unsorted view; the operator picks/types the supplier there. That choice is
  remembered (sender → supplier) so the same sender auto-sorts next time.
- **Sort Supplier is idempotent by default.** A normal run only acts on
  `supplier_sorted` rows; already-`extracted` docs are skipped. An explicit
  **"force re-extract"** option overwrites an existing extraction (mirrors the
  `force` flag on `/api/documents/extract` today) — used after improving a
  supplier's parsing.

## Worked example: two documents through the whole flow

It's a Tuesday and two new supplier emails are sitting in the inbox:

- **Email A** — from `accounts@diageo.com`, subject "Statement of Account May
  2026", with `diageo_stmt_may.pdf` attached.
- **Email B** — from `info@randomcafe.ie`, subject "Hi there", with `scan001.pdf`
  attached (it's actually an invoice, but nothing in the email says so).

Under the *old* system Email B would be **silently dropped** — unknown sender, no
"invoice/statement" keyword. Under this flow, both get captured.

### Stage 1 — click **Capture**

For every inbox PDF the system: pushes the bytes to **R2** (getting a storage
key), writes a **Postgres** row, and marks the Gmail message captured so it's
never grabbed twice. Nothing is read yet — Capture is deliberately dumb.

| id | supplier | document_type | stage      | storage_key       |
|----|----------|---------------|------------|-------------------|
| A  | `Other`  | `unknown`     | `captured` | r2://docs/8f3a…   |
| B  | `Other`  | `unknown`     | `captured` | r2://docs/2b1c…   |

The **Unsorted pile** in the UI is just *"everything where `stage = captured`"* —
both docs show up there.

### Stage 2 — click **Sort**

The system reads each captured PDF and decides only **who it's from**.

- **Doc A**: sender `diageo.com` + "Diageo" in the text → `supplier = Diageo`,
  advances to `supplier_sorted`.
- **Doc B**: unknown sender, no clear supplier → it **can't decide**, stays
  flagged for a human.

| id | supplier | document_type | stage             |
|----|----------|---------------|-------------------|
| A  | `Diageo` | `unknown`     | `supplier_sorted` |
| B  | `Other`  | `unknown`     | `captured` (needs a human) |

Doc A now appears under **Diageo → Unsorted**. Doc B sits in the Unsorted pile
with a "pick a supplier" box. You glance at it, type "Random Cafe" — the row
updates and the system **remembers** `info@randomcafe.ie → Random Cafe`, so that
sender auto-sorts next time. Nothing moved on disk; only the `supplier` column
changed.

### Stage 3 — click **Sort Supplier** (for Diageo)

The deep dive, run per supplier. For Doc A it: classifies the type
(`statement`), extracts every line + the control totals (opening/closing
balance, total due), runs the **arithmetic check** (do the rows add up to the
stated closing balance?), stores the structured data in
`document_financial_facts` (header totals) + `document_financial_rows` (line
items), and advances the stage.

| id | supplier | document_type | stage       | extracted data            |
|----|----------|---------------|-------------|---------------------------|
| A  | `Diageo` | `statement`   | `extracted` | 14 rows · arithmetic ✅ balanced |

Doc A now lives under **Diageo → Statements** and its numbers are queryable. The
`Extracted/Diageo/Statements/STMT-2026-05.json` mirror is generated from those
rows *on demand* if you want to browse it — it is not a maintained second copy.

### Where everything ended up

| Thing                       | Location                                       |
|-----------------------------|------------------------------------------------|
| The PDF bytes               | Cloudflare R2 (one copy, by storage key)       |
| Document metadata + stage   | Railway Postgres `documents` row               |
| The extracted numbers/rows  | Railway Postgres `document_financial_*` tables |
| The "folders" you browse    | Queries — `WHERE supplier=… AND document_type=…` |

### The key mental shift

A document is **one row that climbs a ladder**:

```
captured ──Sort──▶ supplier_sorted ──Sort Supplier──▶ extracted
(unsorted)         (Diageo/Unsorted)                  (Diageo/Statements + data)
```

Each click moves it one rung. "Putting it in a folder" = updating a column. The
PDF only ever moves once (into R2 at capture); after that, all "sorting" is just
changing what the database says about it.
