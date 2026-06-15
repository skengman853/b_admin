# 28 — Bookkeeper Handover, Business Context & Meeting Questions

**Date:** 2026-06-12
**Source:** emails from John Donnelly (back-office bookkeeper) to Bridget Carey
(owner) and Jack, 30 May & 5 Jun 2026.

This document captures what we now know about the *real* job this system does,
who consumes its output, and the deadline — plus the questions to ask John
before he becomes unavailable.

## Who's who

- **Bridget Carey** — owner. Runs two pubs through **Careys Bar Limited**:
  - **Careys Bar** (Athlone) — thriving.
  - **Canal Turn** (Ballymahon) — plateaued ~12 months, not a concern.
  - Business Gmail: **bridgetcareysbar@gmail.com** (invoices arrive here; Drive
    holds exported invoice folders).
- **John Donnelly** — back-office bookkeeper who currently builds the VAT file
  by hand. **Away from mid-June, in Circuit Court 8 July, effectively
  incommunicado until after.** The knowledge we need is in his head.
- **O'Farrell & Co** — the accountancy firm. **They are the end consumer.** The
  deliverable is handed to them.
- **Jack** — taking over John's function and building this tool to do it.

## The real deliverable

Not "a VAT book" — the **"VAT File – Audit Report" function**, handed to
O'Farrell & Co. End-of-June **final handover** is the target. The work "best
needs to complete on a **weekly cycle**" — confirmed by the bookkeeper, not just
our assumption.

This is a strong validation of the system's direction: an audit report is
exactly "**what document chain explains each transaction, and why is its VAT
treated this way**" — which is precisely what the reconciliation engine produces.
The audit report is the export of the reconciliation + VAT categorisation we are
already building.

## Hard facts that shape the build

- **VAT bill heading for ~€30K**; gross margin ~54–55%. The numbers matter to
  the client — the system has the data to show VAT liability and margin *as the
  period builds*, not only at the end.
- **Cash basis.** The current file is "VAT-CASH" — Irish moneys-received basis is
  typical for pubs. (Confirm with John — affects when VAT is counted.)
- **Two pubs, one company.** Careys Bar Ltd operates both; invoices to Canal
  carry "Careys Bar Limited" under "The Canal Turn". The system already
  distinguishes them by pub.
- **Evolving staff list.** Wages/payments to people change constantly across both
  pubs; John uses Excel lookups to manage this. Person-name categories
  (Michael Farrell, Eamon Carey, …) are wages/drawings in the VAT book.
- **Invoice source migration.** Jack takes over "building the updated invoices
  folder" via Bridget's Gmail credentials on his laptop. Our Gmail import
  already does this — point it at bridgetcareysbar@gmail.com.

## Timeline / risk

| When | What | Risk |
|------|------|------|
| Mid-June | Google Meet with John to clear queries | **Last chance** to extract his process before he's gone |
| Mid-June → ~mid-July | John incommunicado | No bookkeeper to ask |
| End June | Final handover of VAT File function to O'Farrell | Hard deadline |

**Implication:** front-load anything that needs John. Get the historical VAT
files (validation ground truth), get Stage A generating a VAT book we can show
him, and get his corrections *at the mid-June meeting* while he can still give
them.

## System suggestions (from this context)

1. **Make the audit report the headline output.** For each transaction: the
   documents that justify it + the VAT treatment + why. That's the report
   O'Farrell want, and it's what reconciliation already assembles.
2. **Live VAT liability + gross margin.** Surface running output VAT (sales) −
   input VAT (purchases) and margin for the open period, so Bridget sees the
   ~€30K forming instead of being surprised.
3. **Point Gmail import at bridgetcareysbar@gmail.com** and reconcile against the
   existing Drive invoice folders (verify nothing is missed vs John's folders).
4. **A graceful "new payee" path.** When a person/payee isn't known yet, the
   system should let the operator name + categorise once and remember it — this
   is the evolving-staff problem, solved by the rules engine.
5. **Match O'Farrell's expected format** for the export, so the handover file
   drops straight into their process.
6. **Capture John's categorisation rules as data**, at the meeting, so his tacit
   knowledge survives his absence (which supplier → which category → which VAT
   band).

## Questions for John (mid-June meeting)

Ordered to extract the knowledge that's about to walk out the door.

### The deliverable
1. Can I see a **completed VAT File – Audit Report** end to end — ideally the
   last few months?
2. What **format/structure do O'Farrell & Co require**? Is there a template they
   expect, or do they take your Excel as-is?
3. What questions does the audit report need to answer for them — what makes it
   "pass"?
4. How is the **VAT return figure** (the ~€30K) derived from the file?

### The weekly cycle
5. Walk me through the **current weekly Excel cycle** start to finish — what you
   open, what you fill in, in what order.
6. How do you decide each transaction's **VAT rate band** (23% resale, 23%
   non-resale, 13.5%, 9%, 0%/exempt)? What's the rule of thumb per category?
7. What's the full **category list**, and which categories have a **fixed VAT
   treatment** (e.g. Insurance → exempt, Fuel → 23%)?
8. How do you split **Renovation/Maintenance** across 23% and 13.5%?
9. Is VAT counted on a **cash (moneys-received) basis** or invoice basis? When
   does a transaction "count"?

### Data sources
10. Exactly which **Gmail labels / Drive folders** hold the invoices, and how are
    they organised? Is *every* supplier in there, or do some arrive on paper?
11. How do **statements vs individual invoices** factor in — do you work from
    invoices, statements, or both?
12. Anything that arrives **outside Gmail** (cash purchases, card receipts,
    direct paper)?

### The two pubs & income / takings
13. Are Careys and Canal **separate VAT returns or combined**? One VAT
    registration or two?
14. **Takings:** we'll provide weekly takings per night. How should they split
    for VAT — drink @23% vs food @13.5%/9%? One figure per night, or already
    broken down? (This sets how output VAT is computed.)
15. How does **output VAT on takings** reconcile against the **lodgements** in
    the bank (card via Valitor/Paymentsense, cash) — and how do you get the
    **gross margin** figure?

### The hard parts
16. What are the **most error-prone / fiddly** parts of the current process —
    where do mistakes usually happen?
17. **Staff/wages** — how do you manage the evolving staff list, and is that
    inside the VAT file or separate payroll?
18. How do you handle **credit notes, settlement discounts** (Diageo accrues
    discount to a sub-account), and **part-payments**?

### Continuity
19. While you're unavailable, **who do I ask** if something comes up?
20. What's the **one thing not written down anywhere** that I most need to know?
21. Can I get **read access to everything** — past files, the invoice folders,
    O'Farrell's contact — before mid-June?

## Immediate next steps (ours)
- [ ] Get the historical hand-made VAT books into the repo as validation data.
- [ ] Build Stage A: generate the VAT book from bank transactions, show it
      side-by-side with the hand-made one, report accuracy %.
- [ ] Connect Gmail import to bridgetcareysbar@gmail.com (after credentials).
- [ ] Bring the Stage A output to the mid-June meeting for John's corrections.
