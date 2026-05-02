# 09 — Frontend Spec

## Overview

Simple React dashboard. Two pages: Login and Dashboard. That's it.

## Pages

### 1. Login / Signup Page (`/`)
- Email + password form
- Toggle between login and signup
- After login → redirect to `/dashboard`

### 2. Dashboard (`/dashboard`)
- Header: app name, user email, logout button
- Gmail connection status (connected / not connected)
- "Connect Gmail" button (if not connected)
- Monthly summary card (total spend, invoice count, pending review)
- Invoice table (main content)
- Month selector (previous/next month)

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────┐
│  📧 Invoice Organizer          user@email.com  [Logout] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ Total Spend  │ │   Invoices   │ │ Pending Review │  │
│  │   £3,420.50  │ │      18      │ │       3        │  │
│  └──────────────┘ └──────────────┘ └────────────────┘  │
│                                                         │
│  ◄ March 2026          April 2026         May 2026 ►   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Supplier          │ Amount  │ Date     │ Status │   │
│  ├───────────────────┼─────────┼──────────┼────────┤   │
│  │ J Smith Plumbing  │ £450.00 │ 28 Apr   │ ⚠️ 87% │   │
│  │ Booker Wholesale  │ £234.50 │ 25 Apr   │ ✅     │   │
│  │ Travis Perkins    │ £1,200  │ 22 Apr   │ ✅     │   │
│  │ Unknown Supplier  │ £89.99  │ 20 Apr   │ ⚠️ 62% │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Invoice Row Interaction

Clicking a pending invoice opens an inline edit/confirm panel:

```
┌─────────────────────────────────────────┐
│ 🧾 Review Invoice                       │
│                                         │
│ Supplier: [J Smith Plumbing     ] ✏️     │
│ Amount:   [£450.00              ] ✏️     │
│ Date:     [2026-04-28           ] ✏️     │
│ Confidence: 87%                         │
│                                         │
│ [✅ Confirm]  [✏️ Save Edit]  [❌ Not an invoice] │
│                                         │
│ 📎 View original PDF                    │
└─────────────────────────────────────────┘
```

## States

### Gmail Not Connected
Show a prominent "Connect Gmail" button with brief explanation:
> "Connect your Gmail to automatically find and organise your invoices."

### No Invoices Yet
After connecting, while initial scan runs:
> "Scanning your inbox... This may take a few minutes."

### Empty Month
> "No invoices found for this month."

## Component Structure

```
src/
├── App.tsx                 # Router setup
├── api.ts                  # API client (axios instance with auth header)
├── pages/
│   ├── Login.tsx           # Login/signup form
│   └── Dashboard.tsx       # Main dashboard page
├── components/
│   ├── SummaryCards.tsx     # Total spend, count, pending
│   ├── InvoiceTable.tsx    # Invoice list table
│   ├── InvoiceRow.tsx      # Single row (expandable for edit)
│   ├── MonthSelector.tsx   # Previous/next month nav
│   └── GmailConnect.tsx    # Connect Gmail button + status
└── hooks/
    ├── useAuth.ts          # Auth state management
    └── useInvoices.ts      # Fetch invoices + summary
```

## Key Behaviours

- Auto-refresh invoice list every 60 seconds (or after confirm/edit)
- Pending invoices (low confidence) shown at top with warning icon
- Confirmed invoices show green tick
- Amounts formatted as GBP (£) with 2 decimal places
- Dates formatted as "28 Apr 2026" (human readable)
- Responsive — works on tablet (business owners check on iPad)

## No Complex Features

- No drag and drop
- No complex filtering/sorting (just month + status)
- No export to CSV (v2)
- No charts or graphs (v2)
- No dark mode
- No notifications/toasts (just inline status)
