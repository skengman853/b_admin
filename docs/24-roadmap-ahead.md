# 24 — Roadmap Ahead

## Goal

Make the system trustworthy enough that month close becomes:

- faster
- calmer
- less forensic

The target is:

> one clear evidence chain per transaction, backed by stored rows and verifier logic

## Current Position

The foundation is now mostly in place:

- archive mostly imported
- extraction runs persisted
- financial facts persisted
- financial rows persisted
- reconciliation suggestions persisted
- verifier layer live
- audit and review pages live

So the roadmap is no longer about proving the product exists.

It is about making the engine sharp and dependable.

## Phase 1 — Finish AI-First Statement Extraction

Priority:

- `Diageo`
- `Heineken`
- `Connacht Bottlers`
- `Bulmers`

Goal:

- recover invoice / credit / payment rows reliably from statements

Success looks like:

- more rows move into `passed` statement settlements
- fewer rows sit in vague support-only states

## Phase 2 — Tighten Persisted Suggestions

Goal:

- make persisted suggestions the real source of truth for the UI

Work:

- keep suggestion refresh flows explicit
- keep verifier reasons compact and operator-friendly
- reduce old ad hoc match derivation in the UI layer

Success looks like:

- the same row looks stable across `/month-audit` and `/review`

## Phase 3 — Make `/month-audit` The Main Operator Surface

Goal:

- the operator should live in `/month-audit`, not in `/review`

Work:

- keep the page minimal
- only show:
  - primary suggestion
  - action
  - main statement
  - main invoice / credit
  - final state
- keep re-extract and `Open PDF` close to the row

Success looks like:

- `/review` becomes the exception tool

## Phase 4 — Close One Full Operating Period Cleanly

Goal:

- finish one real month or VAT period with confidence

Working rule:

- close obvious rows
- do not force weak rows
- treat incomplete evidence honestly

Success looks like:

- the actionable queue is small
- the remaining rows are genuinely hard, not parser noise

## Phase 5 — Learn From Operator Decisions

Goal:

- reduce repeated manual work

Work:

- strengthen rule reuse
- strengthen hidden / rejected doc feedback
- keep owner-handled states standardized

Examples:

- wages
- contract
- hard copy only
- no document expected

Success looks like:

- recurring rows stop reaching deep review

## Phase 6 — Production Hardening

Goal:

- make the system safe to run as a production tool

Work:

- auth hardening
- backup and restore discipline
- monitoring
- deployment safety
- operational recovery steps

This should continue in parallel, but only after the core reconciliation flow stays sharp.

## What We Should Avoid

- more broad UI sprawl
- supplier-specific matching hacks
- fake resolution just to shrink the queue
- trying to turn the product into a full accounting suite

## Recommended Work Order

1. finish AI-first statement extraction
2. keep suggestions/verifier stable
3. make `/month-audit` the default working surface
4. close one operating period cleanly
5. keep production hardening moving underneath

## Definition Of Success

The system is succeeding when:

- imported documents become usable structured rows quickly
- statement suppliers stop feeling mysterious
- the operator trusts the primary suggestion
- most rows can be closed from the audit flow
- the remaining hard rows are genuinely hard
