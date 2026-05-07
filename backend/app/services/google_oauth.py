from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import GmailConnection
from app.services.encryption import decrypt_token, encrypt_token

GOOGLE_API_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]


def build_google_credentials(connection: GmailConnection) -> Credentials:
    return Credentials(
        token=decrypt_token(connection.access_token_encrypted),
        refresh_token=decrypt_token(connection.refresh_token_encrypted),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=GOOGLE_API_SCOPES,
    )


async def get_google_credentials(connection: GmailConnection, db: AsyncSession) -> Credentials:
    credentials = build_google_credentials(connection)

    if not credentials.valid and credentials.refresh_token:
        credentials.refresh(Request())
        connection.access_token_encrypted = encrypt_token(credentials.token)
        if credentials.refresh_token:
            connection.refresh_token_encrypted = encrypt_token(credentials.refresh_token)
        connection.token_expiry = credentials.expiry
        await db.commit()
        await db.refresh(connection)

    return credentials
