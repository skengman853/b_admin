# 05 — Document Classification & Extraction

## Key Shift

Do not start with AI extraction.

Start with the simplest question:

"What is this file, who is it from, and where should it go?"

## Phase 1 Objective

Use a lightweight read of the document to support:

- supplier detection
- document type classification
- naming
- folder routing

This phase does not need full financial field extraction.

## Phase 1 Inputs

Use these signals first:

- sender email domain
- email subject
- attachment filename
- a basic PDF text scan

## Document Types

Start with:

- `invoice`
- `statement`
- `credit_note`
- `unknown`

## Suggested Phase 1 Rules

### Invoice Signals

- subject contains `invoice`, `inv`, `tax invoice`, `vat invoice`
- filename contains `invoice`
- PDF text contains `invoice number`, `invoice no`, `total due`

### Statement Signals

- subject contains `statement`
- filename contains `statement`
- PDF text contains `account statement`, `balance brought forward`

### Credit Note Signals

- subject contains `credit note`, `credit memo`
- filename contains `credit`
- PDF text contains `credit note`

### Ignore Signals

- `transaction`
- `marketing`
- receipts or irrelevant notifications if they do not fit the workflow

## Supplier Detection

Use a layered approach:

1. sender domain mapping
2. known keywords in subject
3. known keywords inside PDF text
4. fallback to `Other`

Example:

```text
candcgroup -> Bulmers
ebilling -> BOC
booker -> Booker
```

## Phase 1 Naming

Target format:

```text
YYYY-MM-DD_Supplier_Type_Reference_Amount.pdf
```

If data is missing, use placeholders:

```text
unknown_date_Bulmers_invoice_unknown_ref_unknown_amount.pdf
```

## Phase 1 Storage Decision

The file should end up in:

```text
Documents/<Supplier>/<Type Folder>/
```

For example:

```text
Documents/Bulmers/Invoices/
Documents/BOC/Statements/
Documents/Other/Credit Notes/
```

## Phase 3 Objective

Only after the local pipeline works should extraction become deeper:

- supplier
- document date
- invoice number
- total
- VAT
- confidence

## Phase 3 Extraction Strategy

1. Extract raw text with `pdfplumber`
2. Use rules and regex first
3. Add supplier-specific parsing where patterns are stable
4. Add OCR fallback only for poor PDFs
5. Add AI only where rules clearly fail

## Why Rules First

Rules are:

- cheaper
- easier to debug
- easier to trust
- easier to improve supplier by supplier

AI can help later, but it should not hide basic pipeline failures.

## Suggested Validation Rules

- totals should be greater than zero
- date should parse cleanly
- VAT should not exceed total
- reference should be optional, not guessed

## Done When

### Phase 1

- a document can be classified and routed correctly

### Phase 3

- a document can be turned into a mostly-correct structured record
