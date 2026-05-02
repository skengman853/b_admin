# 08 — Background Tasks

## Overview

Celery workers handle all async processing: email scanning, invoice extraction, and maintenance tasks.

## Task Queue Setup

- **Broker:** Redis
- **Result backend:** Redis (short TTL, just for status tracking)
- **Concurrency:** 2-4 workers (I/O bound, not CPU bound)
- **Serializer:** JSON

## Tasks

### 1. `tasks.scan_inbox_initial`
Triggered when user first connects Gmail.

```python
@celery.task(bind=True, max_retries=3)
def scan_inbox_initial(self, user_id: str):
    """Fetch last 90 days of emails and process them."""
    gmail_service = get_gmail_service(user_id)
    messages = fetch_messages(gmail_service, query="newer_than:90d", max_results=500)
    
    for msg_id in messages:
        process_single_email.delay(user_id, msg_id)
```

### 2. `tasks.scan_inbox_incremental`
Triggered by Gmail push notification or periodic fallback.

```python
@celery.task(bind=True, max_retries=3)
def scan_inbox_incremental(self, user_id: str, history_id: str):
    """Fetch only new emails since last sync."""
    gmail_service = get_gmail_service(user_id)
    new_messages = fetch_history(gmail_service, history_id)
    
    for msg_id in new_messages:
        process_single_email.delay(user_id, msg_id)
    
    update_history_id(user_id, history_id)
```

### 3. `tasks.process_single_email`
Core task — processes one email for invoice detection + extraction.

```python
@celery.task(bind=True, max_retries=2, rate_limit="10/m")
def process_single_email(self, user_id: str, message_id: str):
    """Process a single email: detect invoice, extract data, store."""
    
    # Skip if already processed
    if is_processed(user_id, message_id):
        return
    
    # Fetch email
    email = fetch_full_email(user_id, message_id)
    
    # Detect if invoice
    if not is_likely_invoice(email.subject, email.body, email.attachments):
        mark_processed(user_id, message_id, is_invoice=False)
        return
    
    # Extract invoice data
    invoice_data = extract_invoice_data(email)
    
    # Upload attachment to S3
    attachment_path = None
    if email.attachments:
        attachment_path = upload_to_s3(user_id, message_id, email.attachments[0])
    
    # Store invoice
    create_invoice(
        user_id=user_id,
        supplier_name=invoice_data["supplier_name"],
        amount=invoice_data["amount"],
        invoice_date=invoice_data["date"],
        confidence_score=invoice_data["confidence"],
        source_email_id=message_id,
        source_email_subject=email.subject,
        attachment_path=attachment_path,
        extracted_text=email.extracted_text
    )
    
    mark_processed(user_id, message_id, is_invoice=True)
```

### 4. `tasks.renew_gmail_watches`
Periodic task — renews Gmail push notification subscriptions.

```python
@celery.task
def renew_gmail_watches():
    """Renew Gmail watch for all active connections. Run daily."""
    connections = get_active_gmail_connections()
    for conn in connections:
        try:
            gmail_service = get_gmail_service(conn.user_id)
            setup_gmail_watch(gmail_service)
        except TokenExpiredError:
            mark_connection_inactive(conn.id)
```

### 5. `tasks.fallback_scan`
Periodic fallback in case push notifications are missed.

```python
@celery.task
def fallback_scan():
    """Scan all active users. Run every 30 minutes as safety net."""
    connections = get_active_gmail_connections()
    for conn in connections:
        scan_inbox_incremental.delay(conn.user_id, conn.history_id)
```

## Periodic Task Schedule (Celery Beat)

```python
CELERY_BEAT_SCHEDULE = {
    "renew-gmail-watches": {
        "task": "tasks.renew_gmail_watches",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3am
    },
    "fallback-scan": {
        "task": "tasks.fallback_scan",
        "schedule": crontab(minute="*/30"),  # Every 30 minutes
    },
}
```

## Error Handling & Retries

| Error | Action |
|-------|--------|
| Gmail API rate limit (429) | Exponential backoff, retry in 60s |
| Gmail token expired | Refresh token, retry |
| Gmail token revoked | Mark connection inactive, notify user |
| OpenAI rate limit | Retry in 30s |
| OpenAI timeout | Retry once, then flag for manual |
| PDF parsing crash | Try Vision fallback, then flag |
| S3 upload failure | Retry 3x, then store without attachment |

### Retry Configuration
```python
@celery.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,        # Exponential backoff
    retry_backoff_max=600,     # Max 10 min between retries
    retry_jitter=True          # Add randomness to prevent thundering herd
)
```

## Rate Limiting

- `process_single_email`: 10 per minute per worker (avoid hammering OpenAI)
- `scan_inbox_incremental`: 5 per minute (avoid Gmail rate limits)

## Monitoring

- Log task start/end with duration
- Track: tasks queued, tasks completed, tasks failed
- Alert on: task queue depth > 100, failure rate > 10%
- Sentry captures all task exceptions automatically
