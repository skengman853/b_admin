import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, EmailStr


# Auth
class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    token: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    gmail_connected: bool
    created_at: datetime


# Invoices
class InvoiceResponse(BaseModel):
    id: uuid.UUID
    supplier_name: str | None
    amount: Decimal | None
    currency: str
    invoice_date: date | None
    confidence_score: float | None
    status: str
    source_email_subject: str | None
    created_at: datetime


class InvoiceUpdateRequest(BaseModel):
    supplier_name: str | None = None
    amount: Decimal | None = None
    invoice_date: date | None = None
    status: str | None = None


class InvoiceListResponse(BaseModel):
    invoices: list[InvoiceResponse]
    total: int
    page: int
    pages: int


# Dashboard
class DashboardSummary(BaseModel):
    month: str
    total_spend: Decimal
    invoice_count: int
    pending_review: int
    currency: str = "GBP"
