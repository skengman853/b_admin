# 06 — Gmail Integration

## Overview

Connect to user's Gmail via OAuth2, fetch emails, detect invoices, and receive push notifications for new emails.

## OAuth2 Flow

### Setup (Google Cloud Console)
1. Create project in Google Cloud Console
2. Enable Gmail API
3. Configure OAuth consent screen (external, production)
4. Create OAuth 2.0 credentials (web application)
5. Set redirect URI: `https://yourdomain.com/api/gmail/callback`

### Scopes Required
```
https://www.googleapis.com/auth/gmail.readonly
```
Read-only. We never send, modify, or delete emails.

### Auth Flow
```
1. User clicks "Connect Gmail"
2. Frontend redirects to: GET /api/gmail/auth-url
3. Backend generates Google OAuth URL with state token
4. User authorises in Google
5. Google redirects to: GET /api/gmail/callback?code=XXX&state=YYY
6. Backend exchanges code for access_token + refresh_token
7. Encrypt tokens, store in gmail_connections table
8. Redirect user back to dashboard
```

### Token Management
```python
from cryptography.fernet import Fernet

# Encrypt before storing
def encrypt_token(token: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(token.encode()).decode()

# Decrypt when needed
def decrypt_token(encrypted: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()
```

- Encryption key stored as environment variable (never in DB)
- Access tokens expire after 1 hour → use refresh token
- If refresh fails (user revoked access) → mark connection inactive, notify user

## Fetching Emails

### Initial Sync (First Connection)
```python
def initial_sync(user_id: str, gmail_service):
    """Fetch last 90 days of emails on first connection."""
    query = "newer_than:90d"
    messages = gmail_service.users().messages().list(
        userId="me", q=query, maxResults=500
    ).execute()
    
    for msg in messages.get("messages", []):
        enqueue_process_email(user_id, msg["id"])
```

### Incremental Sync (Ongoing)
Use Gmail's `history` API to only fetch new emails since last check:
```python
def incremental_sync(user_id: str, gmail_service, history_id: str):
    """Fetch only new emails since last sync."""
    history = gmail_service.users().history().list(
        userId="me",
        startHistoryId=history_id,
        historyTypes=["messageAdded"]
    ).execute()
    
    for record in history.get("history", []):
        for msg in record.get("messagesAdded", []):
            enqueue_process_email(user_id, msg["message"]["id"])
    
    # Update stored history_id
    new_history_id = history.get("historyId")
    update_history_id(user_id, new_history_id)
```

## Push Notifications (Gmail Pub/Sub)

### Why Push Over Polling
- Polling hits rate limits with multiple users
- Push is near-instant (seconds vs 10-15 min delay)
- Less API calls = less chance of quota issues

### Setup
1. Create Google Cloud Pub/Sub topic
2. Grant Gmail publish permission to the topic
3. Create subscription pointing to your webhook

### Watch Request (Per User)
```python
def setup_gmail_watch(gmail_service):
    """Register for push notifications. Must renew every 7 days."""
    request = {
        "topicName": "projects/your-project/topics/gmail-notifications",
        "labelIds": ["INBOX"]
    }
    response = gmail_service.users().watch(userId="me", body=request).execute()
    return response["historyId"], response["expiration"]
```

### Webhook Handler
```python
@app.post("/api/webhooks/gmail")
async def gmail_webhook(request: Request):
    """Receives push notification when user gets new email."""
    data = await request.json()
    
    # Decode Pub/Sub message
    message = base64.b64decode(data["message"]["data"]).decode()
    payload = json.loads(message)
    
    email_address = payload["emailAddress"]
    history_id = payload["historyId"]
    
    # Find user by Gmail address, trigger incremental sync
    user = get_user_by_gmail(email_address)
    if user:
        enqueue_incremental_sync(user.id, history_id)
    
    return {"status": "ok"}
```

### Watch Renewal
- Gmail watch expires every 7 days
- Set up a Celery periodic task to renew all active watches daily

## Rate Limits

| Quota | Limit |
|-------|-------|
| Queries per day | 1,000,000,000 (not a concern) |
| Queries per user per second | 250 |
| Messages.get per user per second | 50 |
| History.list per user per second | 50 |

For a small business app, you won't hit these. But implement exponential backoff anyway.

## Email Processing Flow

```python
def process_email(user_id: str, message_id: str):
    """Process a single email for invoice detection."""
    
    # 1. Check if already processed
    if is_already_processed(user_id, message_id):
        return
    
    # 2. Fetch full email
    msg = gmail_service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    
    # 3. Extract subject, body, attachments
    subject = get_header(msg, "Subject")
    body = get_body_text(msg)
    attachments = get_attachments(msg)
    
    # 4. Check if likely an invoice
    if not is_likely_invoice(subject, body, attachments):
        mark_processed(user_id, message_id, is_invoice=False)
        return
    
    # 5. Extract invoice data
    invoice_data = extract_invoice(subject, body, attachments)
    
    # 6. Store
    store_invoice(user_id, message_id, subject, invoice_data)
    mark_processed(user_id, message_id, is_invoice=True)
```

## Security Considerations

- Only request `gmail.readonly` scope
- Encrypt tokens at rest
- Validate webhook signatures (verify Pub/Sub origin)
- Never log email content (only metadata for debugging)
- User can disconnect Gmail at any time (revoke + delete tokens)
