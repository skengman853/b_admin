# 05 — PDF & Invoice Extraction

## Overview

Invoices from small business suppliers come in many formats:
- Clean digital PDFs (SaaS tools, accounting software)
- Scanned paper invoices (builders, tradespeople)
- Photos of handwritten invoices (forwarded via email)
- Thermal receipt scans (cash & carry)
- .docx attachments (rare but happens)

The extraction pipeline must handle all of these.

## Extraction Pipeline

```
Email received
    │
    ▼
┌─────────────────────────────┐
│ 1. Check email body/subject │
│    for invoice keywords     │
└─────────────────────────────┘
    │
    ├── No match → Skip, mark as processed
    │
    ▼
┌─────────────────────────────┐
│ 2. Has attachments?         │
│    PDF / image / docx       │
└─────────────────────────────┘
    │
    ├── No attachment → Extract from email body only
    │
    ▼
┌─────────────────────────────┐
│ 3. Extract text (pdfplumber)│
└─────────────────────────────┘
    │
    ├── Got good text (>100 chars) → Send to OpenAI (text mode, cheap)
    │
    ▼
┌─────────────────────────────┐
│ 4. Convert to image         │
│    Send to OpenAI Vision    │
└─────────────────────────────┘
    │
    ├── Got structured data → Store
    │
    ▼
┌─────────────────────────────┐
│ 5. Failed → Flag for manual │
│    review (status: pending) │
└─────────────────────────────┘
```

## Invoice Detection Keywords

Check email subject AND body (case-insensitive):
```
invoice, receipt, bill, statement, payment due,
amount due, total due, remittance, pro forma,
purchase order, PO number, tax invoice, VAT invoice
```

Also trigger on:
- PDF attachments with "invoice" in filename
- Emails from known supplier addresses (learned over time)

## Text Extraction (Layer 1 — Free, Fast)

```python
import pdfplumber
import io

def extract_text_from_pdf(pdf_bytes: bytes) -> str | None:
    """Try direct text extraction. Works for digital PDFs."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = pdf.pages[:3]  # First 3 pages max
            text = "\n".join(page.extract_text() or "" for page in pages)
        
        if text.strip() and len(text.strip()) > 100:
            return text.strip()
        return None
    except Exception:
        return None
```

## Vision Extraction (Layer 2 — For Scans/Photos)

```python
import base64
from pdf2image import convert_from_bytes

def extract_with_vision(pdf_bytes: bytes) -> dict:
    """Convert PDF to image, send to OpenAI Vision."""
    images = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=200)
    
    # Convert to PNG bytes
    buffer = io.BytesIO()
    images[0].save(buffer, format="PNG")
    image_b64 = base64.b64encode(buffer.getvalue()).decode()
    
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": EXTRACTION_PROMPT},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{image_b64}"
                }}
            ]
        }],
        temperature=0
    )
    return parse_ai_response(response.choices[0].message.content)
```

## AI Extraction Prompt

```
Extract invoice details from the following content.

Return ONLY valid JSON with these fields:
{
    "supplier_name": "Company or person name on the invoice",
    "amount": 0.00,
    "date": "YYYY-MM-DD",
    "confidence": 0.85
}

Rules:
- "amount" must be the TOTAL / GRAND TOTAL (including VAT if shown)
- "date" is the invoice date, not due date
- "confidence" is how sure you are (0.0 to 1.0)
- If a field cannot be determined, use null
- Do NOT guess — if unclear, set confidence low and field to null
```

## Handling Different File Types

| Type | How to handle |
|------|--------------|
| `.pdf` (text-based) | pdfplumber → OpenAI text extraction |
| `.pdf` (scanned) | pdf2image → OpenAI Vision |
| `.png` / `.jpg` | Direct to OpenAI Vision |
| `.docx` | python-docx → extract text → OpenAI text extraction |
| `.xlsx` / `.csv` | Skip for MVP (rare for invoices) |
| Password-protected PDF | Skip, flag for manual review |

## File Size & Safety Limits

- Max attachment size: **10MB**
- Max pages processed: **3** (invoice data is on page 1)
- Max image resolution for Vision: **2048px** (resize if larger)
- Timeout per extraction: **30 seconds**

## Deduplication

Before processing, check:
1. Has this `gmail_message_id` been processed before? → Skip
2. After extraction, check for duplicate: same supplier + same amount + same date (±1 day) → Flag as potential duplicate

## Cost Estimates

| Volume | Text extraction cost | Vision cost | Total/month |
|--------|---------------------|-------------|-------------|
| 50 invoices/month | ~£0.01 | ~£0.50 | ~£0.51 |
| 200 invoices/month | ~£0.04 | ~£2.00 | ~£2.04 |
| 500 invoices/month | ~£0.10 | ~£5.00 | ~£5.10 |

Assuming 60% need Vision (scanned), 40% are digital PDFs.

## Error Handling

- PDF parsing fails → Try Vision fallback
- Vision fails → Store with status "pending", no extracted data, flag for manual entry
- OpenAI returns invalid JSON → Retry once with stricter prompt, then flag
- OpenAI rate limited → Exponential backoff, retry via Celery
- Timeout → Re-queue task with lower priority
