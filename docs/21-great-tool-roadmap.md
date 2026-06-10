# 21 — Great Tool Roadmap

This document is still useful as a product-quality roadmap layer.

For the current consolidated roadmap, start with:

- [24-roadmap-ahead.md](24-roadmap-ahead.md)

## Goal

Make the product great at one thing:

> show one trustworthy evidence chain for each transaction quickly enough that month close stops feeling forensic

That means the system should become excellent at:

1. extracting statement and invoice data reliably
2. presenting one primary evidence path instead of noisy alternatives
3. showing missing evidence explicitly
4. letting the operator switch between transaction-first and statement-first review
5. running safely in production

## Phase 1 — Statement Workbench

Goal:

- review supplier account statements directly instead of only through individual transactions

What it should do:

- open statements by supplier and month
- show statement period, kind, refs, and settlement groups
- show which invoice refs are already imported
- show which refs are still missing
- show likely bank transactions the statement explains

Why first:

- this is the cleanest way to improve both extraction quality and operator trust
- it also makes missing-document vs bad-parser issues obvious

Status:

- initial statement workbench API and UI implemented

## Phase 2 — Statement Extraction Quality

Priority suppliers:

- Diageo
- Heineken
- Connacht
- Bulmers

Goal:

- make statement rows reliable enough to build real settlement groups consistently

Work:

- improve AI extraction for table-heavy statements
- preserve row structure:
  - invoice ref
  - credit ref
  - payment ref
  - date
  - due date
  - amount
- reduce false “support-only” states where the statement really contains enough math

Implementation detail:

- use the structured data build plan in `docs/22-ai-reconciliation-data-plan.md`

Success signal:

- more rows move from vague support-doc review into explicit statement settlement chains

## Phase 3 — Primary Evidence Mode

Goal:

- make the top of each transaction view feel obvious

Top-level block should show only:

- supplier
- primary statement
- primary invoice / credit group
- missing pieces
- recommended next action

Everything else should be secondary:

- alternate statements
- extra supplier-period invoices
- raw support cards

Success signal:

- the operator can understand a transaction without reading long explanation text

## Phase 4 — Learned Resolution Layer

Goal:

- make the product improve from repeated operator decisions

Work:

- strengthen rule templates
- make hidden-doc and “not this transaction” feedback reusable
- improve recurring handling for:
  - wages
  - contracts
  - hard copy only
  - no document expected

Success signal:

- fewer recurring rows ever reach deep review

## Phase 5 — Production Hardening

Goal:

- make the system safe to run as an actual production tool

Work:

- auth hardening
  - restrict signup
  - bootstrap admin flow
  - tighten JWT behaviour
- deployment hardening
  - production compose/runtime
  - reverse proxy / HTTPS
  - managed Postgres / Redis
- data safety
  - backups
  - restore drills
  - retention policy
- observability
  - Sentry
  - structured logs
  - worker visibility

Status:

- initial runtime hardening is done:
  - `app_env`
  - startup validation
  - `/ready`
  - `docker-compose.prod.yml`

## Recommended Work Order

1. use the statement workbench to expose real statement gaps
2. improve extraction for the worst statement families
3. tighten primary evidence mode in `/review`
4. improve learned rules and hidden-doc reuse
5. finish production hardening

## Definition Of Great

The tool is great when:

- most rows are obviously green or yellow at the register level
- statement suppliers are explainable without manual detective work
- missing evidence is explicit
- the operator can trust the evidence chain
- production deployment is boring
