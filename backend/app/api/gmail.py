from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import User, GmailConnection
from app.services.encryption import encrypt_token

router = APIRouter(prefix="/api/gmail", tags=["gmail"])

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _create_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    return flow


@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    flow = _create_flow()
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=str(user.id),
    )
    return {"url": url}


@router.get("/callback")
async def gmail_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    flow = _create_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # Get user email from Gmail API
    from googleapiclient.discovery import build
    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute()
    gmail_email = profile["emailAddress"]

    user_id = state

    # Upsert gmail connection
    result = await db.execute(
        select(GmailConnection).where(GmailConnection.user_id == user_id)
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.gmail_email = gmail_email
        conn.access_token_encrypted = encrypt_token(credentials.token)
        conn.refresh_token_encrypted = encrypt_token(credentials.refresh_token)
        conn.token_expiry = credentials.expiry
        conn.is_active = True
    else:
        conn = GmailConnection(
            user_id=user_id,
            gmail_email=gmail_email,
            access_token_encrypted=encrypt_token(credentials.token),
            refresh_token_encrypted=encrypt_token(credentials.refresh_token),
            token_expiry=credentials.expiry,
            is_active=True,
        )
        db.add(conn)

    await db.commit()

    # TODO: Trigger initial inbox scan via Celery task

    return RedirectResponse(url=f"{settings.frontend_url}/dashboard")


@router.delete("/disconnect")
async def disconnect_gmail(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GmailConnection).where(GmailConnection.user_id == user.id)
    )
    conn = result.scalar_one_or_none()
    if conn:
        await db.delete(conn)
        await db.commit()
    return {"message": "Gmail disconnected"}
