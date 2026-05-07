# 01 — Project Overview

## Product Name
Invoice Auto-Organizer

## One-Line Description
Automatically pull document attachments from Gmail, classify them, and organize them into a system that can later be searched, extracted, and matched to bookkeeping records.

## Core Problem

The real problem is not "build a dashboard."

The real problem is:

- invoices and statements arrive by email
- attachments are buried in Gmail threads
- files end up scattered across downloads, Drive folders, and inbox search
- bookkeeping work later depends on finding the right document quickly

This product is meant to remove that manual document-chasing workflow.

## Target Users

- Small business owners
- Bookkeepers
- Admin staff handling VAT or monthly reconciliations
- Businesses that currently search Gmail and Drive manually for invoices or statements

## Core Value Proposition

"Stop digging through email for supplier documents."

The system should:

- collect likely finance documents from Gmail
- organize them consistently
- make them easy to find
- later connect them to structured bookkeeping records

## Revised User Flow

1. User connects Gmail
2. System scans recent emails
3. PDF attachments are downloaded locally
4. Documents are classified by supplier and type
5. Files are stored into a clean folder structure
6. Later, the same documents sync to Drive
7. Later, fields are extracted from the documents
8. Later, documents are matched to Excel or VAT transactions
9. Later, a UI makes all of this easy to review

## MVP Success Criteria

The first real MVP is local pipeline success, not SaaS polish.

- [ ] Gmail can be connected
- [ ] Recent emails can be scanned
- [ ] Relevant PDFs can be downloaded
- [ ] Documents are classified correctly enough to be useful
- [ ] Files are saved into predictable local folders
- [ ] Duplicate processing is avoided

## What We Are Not Building First

- Full multi-user SaaS
- Advanced AI extraction before the pipeline is stable
- A polished dashboard before the documents are organized correctly
- Google Drive before the local pipeline is trustworthy
- Excel matching before documents are consistently named and stored

## Later Product Stages

After the local document pipeline works:

1. Sync the organized files to Google Drive
2. Extract structured fields such as date, total, VAT, and reference
3. Match documents to Excel or VAT records
4. Add a simple UI
5. Expand into production SaaS features only after the workflow is proven
