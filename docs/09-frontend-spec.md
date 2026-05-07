# 09 — Frontend Spec

## Important Context

Frontend is not Phase 1.

The local document pipeline must work before time is spent on a serious UI.

## Current Situation

The backend currently redirects Gmail OAuth callbacks to:

```text
http://localhost:3000/dashboard
```

If no frontend is running there, the redirect fails visually, but Gmail token storage can still succeed.

That means:

- frontend is optional right now
- browser redirect failures after OAuth are not the core blocker

## Phase 5 Goal

Build the minimum UI needed to make the document workflow usable by a non-technical person.

## Core Pages

### 1. Documents

Purpose:

- browse all stored documents
- filter by supplier, type, and date
- open local or Drive-backed files quickly

Suggested fields:

- supplier
- type
- date
- amount if extracted
- source file name
- storage location

### 2. Suppliers

Purpose:

- group documents by supplier
- see which suppliers are noisy or inconsistent

### 3. Unlinked Transactions

Purpose:

- show imported bookkeeping rows that do not yet have a matched document
- surface suggested matches

### 4. Monthly Summary

Purpose:

- show counts and spend totals
- highlight unmatched or uncertain items

## Key Actions

- view PDF
- open Drive link
- copy link
- mark document as linked
- correct supplier
- correct document type

## UX Principles

- fast retrieval matters more than visual polish
- document clarity matters more than charts
- filters and grouping matter more than animation
- matching review should be simple to understand

## What the First UI Does Not Need

- advanced charts
- dark mode
- complicated notifications
- full admin settings
- broad SaaS account management

## Recommendation

Until Phase 5 begins, keep the UI requirement minimal:

- Swagger for API checks
- terminal commands for debugging
- local folder inspection for proof of correctness
