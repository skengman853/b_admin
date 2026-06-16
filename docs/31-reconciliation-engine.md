# 31 — The Reconciliation Engine (the middle man)

This is the join. Docs [29](29-pipeline-stages.md) and [30](30-transaction-importer.md)
build the two halves; this engine answers the one question the whole system
exists for:

> **What document explains this bank transaction?**

```
   DOCUMENTS (stage = extracted)              TRANSACTIONS (stage = imported)
   invoices · statements · credit notes       bank debits / credits
            │                                            │
            └──────────────► RECONCILIATION ◄────────────┘
                 propose a match → verify the numbers → ask the operator
```

Unlike 29 and 30 (which redesign existing flows), most of this engine **already
exists** — `transaction_reconciliation.py` and `reconciliation_suggestions.py`.
This doc writes down how it works so it's understandable and so the staged model
plugs into it cleanly.

> **Note:** the existing engine (four match types, deterministic verifier, six
> resolution buckets) is described in full further down. But the operator's
> intended model is **much simpler** — a few plain rules. That simpler model is
> the **target**; the richer engine below is the fallback/reference. Build toward
> the rules in the next section.

## The matching rules (simplified target model)

The whole thing reduces to: **for a transaction, look only inside that
supplier's invoices, and find the one with the exact same amount, dated just
before the payment.** In detail:

1. **Supplier-scoped.** A transaction only ever matches documents from its **own
   supplier**. Bulmers payment → only Bulmers invoices.
2. **Exact amount, one-to-one (the normal case).** Find the supplier's invoice
   whose amount **exactly equals** the transaction amount. That's the match.
3. **Invoice must pre-date the payment.** You pay *after* being invoiced, so the
   invoice date is always **before** the transaction date.
4. **Closest-prior wins.** If several invoices share the exact amount, pick the
   one **dated closest before** the transaction. If it still can't be picked
   cleanly → **flag it to the operator**, don't guess.
5. **Date window from payment terms.** Use the invoice's own due date / the
   supplier's usual "pay X days after invoice" to set the *expected* payment date
   and bound the search. (Bulmers, e.g., tends to be a fixed number of days.) If
   an invoice carries no terms, fall back to a default window.
6. **Exact only — never approximate.** If no invoice exactly matches the amount,
   do **not** match. A near-miss is **alerted** as a possible counting error, and
   a no-match is **left for the operator**. No silent guessing.
7. **Statements are parent → child.** A parsed statement is split into its
   invoice lines (children), tied to the standalone invoices already extracted.
   When a transaction matches one of those child invoices, the **statement
   (parent) is matched too**. *(Lovell — the one supplier with many invoices per
   payment — is this case; exact mechanism still to be decided, see open items.)*
8. **Same-month supporting docs attach.** Credit notes and similar in the **same
   month** as the transaction are attached to it as supporting evidence.

This maps onto the existing engine as: rule 2–6 = a tightened
`direct_invoice_match` (exact-only, supplier-scoped, closest-prior); rule 7 =
`statement_settlement` via parent/child; rule 8 = `supporting_docs_only`. The
deterministic "do the numbers add up" check still applies — here it's simply
"amount is exactly equal."

## Same core principle: DB is truth, never auto-commit

The engine **proposes**; the operator **confirms**. Two row types capture that:

- **`reconciliation_suggestions`** (+ `_items`) — what the machine *thinks*
  matches. Status `suggested`. Disposable: safe to delete and rebuild.
- **`transaction_document_links`** — what's *confirmed*. The real, durable
  answer. Created when the operator accepts a suggestion (or when a match is
  exact and high-confidence enough to auto-link).

Re-running the matcher only ever rewrites *suggestions*; confirmed *links* are
never silently overwritten.

## The flow (button: "Reconcile" — per month)

For each transaction in the period:

1. **Gather candidates** — find documents that could plausibly explain it:
   same supplier, amount in range, date in a window around the transaction.
2. **Propose a suggestion** — build one of the four match types below.
3. **Verify deterministically** — do the *stored numbers actually add up* to the
   bank amount? Produces `verifier_status`: `passed` / `partial` / `failed`.
   This is the trust guard — nothing is called a clean match on vibes.
4. **Classify into a resolution bucket** — translate the result into a plain
   "what should the operator do" label.
5. **Persist** the suggestion, stamped with `matcher_version` + `extractor_version`.

Nothing is auto-confirmed except exact, high-confidence links. Everything else
lands in front of the operator with a reason.

## The four kinds of match (`suggestion_type`)

| Type | Plain meaning |
|------|---------------|
| `direct_invoice_match` | One bank payment ↔ one invoice/credit note. Amounts line up. |
| `statement_settlement` | One bank payment ↔ a **group** of rows on a statement (invoices + credit notes − settlement discount) that sum to the payment. This is the Diageo/Heineken case. |
| `supporting_docs_only` | Related supplier documents exist and probably explain it, but no clean settlement group could be built. Needs human eyes. |
| `rule_resolution` | **No document expected** — a `transaction_rule` says this line is a bank charge, wages, transfer, etc. Resolved without a document. |

## The deterministic verifier — why matches are explainable

The verifier (`_evaluate_deterministic_verifier`) is the heart of "trust." It
takes a proposed suggestion and checks the **stored amounts** against the bank
amount:

- `direct_invoice_match` → do the exact invoice/credit components **sum to the
  bank amount**? Yes → `passed`. Components exist but don't fully add up →
  `partial`. Nothing exact → `failed`.
- `statement_settlement` → is there a payment row matching the bank amount, *and*
  linked invoice/credit components, *and* does the statement **internally
  balance** (its own arithmetic check from doc 29)? All yes → `passed`. If the
  statement doesn't balance, it's capped at `partial` — its rows aren't trusted.
- `rule_resolution` → `passed` (a human rule decided it).

The point: a suggestion is only ever `passed` when the maths actually closes.
That's what makes every match auditable — the operator sees *why*, not just a
score.

## The resolution buckets — the operator's to-do list

Each transaction gets sorted into exactly one bucket
(`_populate_resolution_guidance`), which is what the review UI groups by:

| Bucket | What it means / what to do |
|--------|----------------------------|
| `confirm_match` | A clean match is ready — just confirm it. |
| `complete_partial_match` | Some coverage exists, but the full amount isn't explained yet. |
| `review_supporting_docs` | Statement/account-settlement docs exist; review and link. |
| `no_document_expected` | Looks like a bank/internal charge — no document needed. |
| `awaiting_document` | No matching document found yet — chase it or wait. |
| `needs_matcher_improvement` | Related docs are nearby but the matcher couldn't resolve cleanly — a signal to improve matching (or a fixture to add). |

## Suggestion → confirmed link

When the operator accepts a suggestion (in `/review`), a
`transaction_document_link` is written: it records the document, the role
(`invoice` / `credit_note` / `statement` / …), the amount applied, the score, and
the reason. That link is the durable "this payment is explained by these
documents" fact the VAT book and audit views read from.

## Versioning & re-running

Every suggestion stores `matcher_version` and `extractor_version`. When the
matcher logic or the extraction improves, bump the version; stale suggestions are
recognised as out-of-date and rebuilt on the next run. Re-running "Reconcile" for
a month is therefore **safe and idempotent** — it refreshes suggestions without
touching confirmed links.

## Storage model

| Thing | Where it lives |
|-------|----------------|
| Proposed matches | Railway Postgres `reconciliation_suggestions` (+ `_items`) |
| Confirmed matches | Railway Postgres `transaction_document_links` |
| "No document expected" rules | Railway Postgres `transaction_rules` |
| Audit trail of operator actions | Railway Postgres `transaction_review_events` |

Same as 29/30: all truth in Railway Postgres. (Suggestions are derived data —
they can always be rebuilt from documents + transactions.)

## Worked example (continuing the Diageo story)

From doc 29, the **Diageo May statement** was extracted: 14 rows, arithmetic
balanced ✅. From doc 30, the **bank CSV** imported a line: `02 Jun 2026 · DIAGEO
· debit €2,026.00`.

You click **Reconcile** for June:

1. **Gather** — the engine finds Diageo documents near that date and amount: the
   May statement and its component invoices/credit notes.
2. **Propose** — the statement has a payment row of €2,026.00 whose linked
   invoice rows (−​a credit note, − settlement discount) sum to €2,026.00 → it
   builds a **`statement_settlement`** suggestion.
3. **Verify** — payment row matches the bank amount ✅, components are linked ✅,
   and the statement internally balances ✅ → `verifier_status = passed`.
4. **Classify** → bucket `confirm_match`.
5. **Persist** — a `reconciliation_suggestion` (type `statement_settlement`,
   verifier `passed`) with one item per row.

In `/review` the June Diageo line shows up under **Confirm match** with the
explanation: *"a statement payment row matches the bank amount and has linked
invoice/credit components."* You click confirm → a `transaction_document_link`
is written → the VAT book now knows this €2,026.00 is explained by that
statement's documents.

If the statement *hadn't* balanced, the same suggestion would be capped at
`partial` and land in **review supporting docs** instead — the engine refuses to
present untrustworthy rows as a clean match.

## What changes from today

1. **It reads from the staged model** — candidates come from documents at stage
   `extracted` (doc 29) and transactions at stage `imported` (doc 30). No other
   change to inputs.
2. **Nothing else structurally** — the engine, the four match types, the
   verifier, the buckets, and the suggestion/link split all already exist.
3. (Opportunity) **The matcher is one 3,375-line file.** It's the strongest
   candidate for the "break a service into smaller testable pieces" goal: the
   four match-type builders and the verifier could each become independently
   testable units fed a transaction + candidate documents.

## Decisions locked

- **Simpler rules are the target** (see "The matching rules" above); the richer
  four-type/verifier/bucket engine is the fallback/reference.
- **Supplier-scoped** — a transaction only matches its own supplier's documents.
- **Exact amount only** — no tolerance. Near-miss → alert (possible counting
  error); no match → leave for the operator. No silent guessing.
- **Closest-prior-date tie-break** — invoice must pre-date the payment; nearest
  before wins; ambiguous → flag to operator.
- **Window from payment terms** — expected payment ≈ invoice date + supplier
  terms, with a default fallback window when terms are absent.
- **Statements are parent/child** — matching a child invoice pulls in the parent
  statement.
- **Propose, don't auto-commit** — suggestions are machine output; links are
  confirmed truth.
- **Truth in Railway Postgres**; suggestions are rebuildable derived data;
  re-running is idempotent (refreshes suggestions, never touches links).

## Still open (decide next)

- **Lovell (many invoices → one payment)**: statement-driven (match the statement
  total, link the invoices it lists) or work out the invoice combination
  ourselves (subset-sum, riskier)? — *operator coming back on this.*
- **Default fallback window**: when an invoice has no payment terms, how many
  days before the transaction do we still consider? (e.g. 60–90.)
- **Reading payment terms**: do we extract the due date / terms off each invoice
  during extraction (doc 29) to drive the window, or hold a per-supplier term?
- **Same-month credit notes**: when a supplier has several transactions in one
  month, which transaction does a same-month credit note attach to?
- **Run scope**: per-month button only, or also a "reconcile everything
  outstanding" run?
- **Matcher refactor**: split the 3,375-line matcher into testable per-rule units
  now, or after the staged pipeline (29/30) is built?
