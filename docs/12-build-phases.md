# 12 — Build Phases & Execution Order

## Overview

This roadmap is aligned to the real problem being solved:

1. Pull documents from Gmail
2. Classify and organize them correctly
3. Extract structured data
4. Match them to bookkeeping records
5. Add a usable interface
6. Only then harden for SaaS / production

The build order is intentionally practical:

- prove the pipeline locally first
- add cloud storage second
- add structured extraction third
- solve matching before spending time on polish
- leave multi-user SaaS concerns until the workflow is real

---

## Phase 1 — Local Document Pipeline

Status:
- complete
- completion note: [docs/14-phase-1-completion.md](14-phase-1-completion.md)

### Goal

Prove the core pipeline works end-to-end:

`Gmail -> PDF -> classified -> stored in correct folders`

### Tasks

1. Gmail integration
- Connect to Gmail API
- Fetch recent emails, starting with the last 7-30 days
- Retrieve subject, sender, and attachments

2. Email filtering
- Define include rules such as `invoice`, `statement`, `inv`
- Define exclude rules such as `transactions`, `marketing`, and irrelevant email patterns
- Filter based on subject and presence of PDF attachments

3. Attachment handling
- Extract PDF attachments from matching emails
- Handle multiple attachments per email
- Save them temporarily to `temp_pdfs/`

4. Supplier detection
- Map sender domains to suppliers
- Fallback to keyword matching in subject or PDF text
- Route unknown suppliers to `Other`
- Mark uncertain cases for review

5. Document type classification
- Detect `invoice`, `statement`, `credit note`, `receipt`, or `unknown`
- Use subject, filename, and basic PDF text scanning

6. Folder structure creation
- Create a local structure like:

```text
Documents/
  Supplier/
    Invoices/
    Statements/
    Credit Notes/
    Receipts/
    Other/

Documents/
  Needs Review/
    Supplier/
      Invoices/
      Statements/
      Credit Notes/
      Receipts/
      Other/
```

- Create missing folders automatically

7. File naming
- Use a standard format:

```text
YYYY-MM-DD_Supplier_Type_Reference_Amount.pdf
```

- If data is missing, use placeholders such as `unknown_date`

8. Local file storage
- Move processed PDFs into the correct folder
- Prevent accidental overwrites
- Handle duplicate filenames safely

9. Logging and tracking
- Log emails scanned, files saved, and files skipped
- Track processed messages in `processed_emails.json`
- Expose scan summary and review-needed files through lightweight API/reporting endpoints

### Done When

- You run the script
- Emails are scanned
- PDFs are downloaded
- Documents are classified correctly
- Files land in a clean local folder structure
- Uncertain files are clearly routed to a review bucket
- The user can inspect scan totals and review items without opening raw JSON
- You can visually verify the result without any UI

### Do Not Include

- Google Drive
- Database
- AI extraction
- Frontend
- Excel integration

---

## Phase 2 — Cloud Storage Integration

### Goal

Replace the manual Google Drive workflow.

### Tasks

1. Google Drive setup
- Connect to Google Drive API
- Create a root `Documents/` folder

2. Folder sync logic
- Mirror the local structure in Drive
- Organize by `Supplier -> Type -> Year -> Month`
- Auto-create missing folders

3. Upload pipeline
- Upload processed PDFs to the correct Drive folder
- Prevent duplicate uploads

4. Link generation
- Generate a Drive link for each uploaded document
- Store the link in the system

5. Basic data storage
- Add a simple database such as SQLite or Postgres
- Store supplier, document type, file name, file link, and processed timestamp

6. Deduplication
- Avoid reprocessing the same email
- Track processed Gmail message IDs in the system of record

### Done When

- A new email arrives
- Its PDF is uploaded to the right Drive folder
- A link is stored for later use

---

## Phase 3 — Data Extraction

### Goal

Turn stored documents into structured, searchable records.

### Tasks

1. PDF text extraction
- Extract raw text from PDFs
- Handle digital PDFs first
- Add OCR fallback later if needed

2. Field extraction, rules first
- Extract supplier, date, total, VAT, and invoice number
- Start with regex and keyword-based logic

3. Supplier-specific handling
- Add logic for suppliers such as Bulmers, TCC, and BOC
- Handle layout differences incrementally

4. Document type refinement
- Improve classification accuracy
- Better distinguish invoices, statements, and credit notes

5. Data validation
- Validate dates and totals
- Flag uncertain outputs

6. Structured record storage
- Save supplier, type, date, total, VAT, invoice number, Drive link, and confidence score

### Done When

- PDF in
- Structured record out
- Data is mostly correct, roughly 80-90 percent

---

## Phase 4 — Matching to Excel

### Goal

Solve the real pain point: linking documents to bookkeeping transactions.

### Tasks

1. Excel reader
- Load the VAT Excel file
- Extract date, description, and amount

2. Matching engine
- Match on amount, date proximity, and supplier similarity

3. Confidence scoring
- Score matches as `High`, `Medium`, or `Low`

4. Suggestion output
- Generate suggested matches from transaction to document link

5. Output format
- Start with either a simple web page or a CSV export

### Done When

- An Excel row is loaded
- The system suggests a likely matching invoice
- The user can open or copy the document link easily

---

## Phase 5 — Dashboard UI

### Goal

Make the system usable without technical knowledge.

### Tasks

1. Basic UI setup
- Add a simple frontend
- Connect it to the backend API

2. Core pages
- Documents
- Suppliers
- Unlinked Transactions
- Monthly Summary

3. Documents page
- List all documents
- Filter by supplier, type, and date

4. Suppliers page
- Group documents by supplier

5. Unlinked Transactions page
- Show unmatched Excel rows
- Show suggested matches

6. Monthly Summary page
- Show spend totals
- Show breakdown by supplier

7. Actions
- View PDF
- Copy Drive link
- Mark as linked

### Done When

- A non-technical user can find invoices quickly
- A user can link documents to Excel records
- A user can review summaries without touching scripts

---

## Phase 6 — Production / SaaS

### Goal

Make the system stable, scalable, and usable by multiple businesses.

### Tasks

1. Backend and infrastructure
- Docker Compose or equivalent production setup
- Postgres and Redis
- Worker system such as Celery

2. Authentication
- User accounts
- JWT auth
- Multi-user support

3. Multi-business support
- Separate data per business
- Support multiple Gmail accounts

4. Automation
- Gmail push notifications
- Background processing

5. Monitoring
- Logging
- Error tracking
- Alerts

6. Deployment
- Cloud hosting
- Domain and SSL
- Backups

### Done When

- The system is live
- Businesses can sign up
- Gmail can be connected
- Documents are processed automatically

---

## Guiding Principles

1. Solve the real workflow before polishing architecture.
2. Start local, then automate, then scale.
3. Prefer visible outputs over abstract plumbing.
4. Use rules first; add AI only where it genuinely improves accuracy.
5. Build from pipeline to data to matching to product to SaaS.
