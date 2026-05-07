import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field


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


# Pipeline
class PipelineScanRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    max_messages: int = Field(default=50, ge=1, le=500)
    force: bool = False


class PipelineStoredFile(BaseModel):
    attachment_name: str
    supplier: str
    document_type: str
    document_date: str | None = None
    reference: str | None = None
    amount: str | None = None
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    saved_path: str


class PipelineMessageResult(BaseModel):
    message_id: str
    sender: str
    subject: str
    status: str
    reason: str | None = None
    files: list[PipelineStoredFile] = Field(default_factory=list)


class PipelineScanResponse(BaseModel):
    scanned_messages: int
    processed_messages: int
    skipped_messages: int
    saved_files: int
    needs_review_messages: int = 0
    needs_review_files: int = 0
    files_by_supplier: dict[str, int] = Field(default_factory=dict)
    files_by_type: dict[str, int] = Field(default_factory=dict)
    tracking_file: str
    results: list[PipelineMessageResult] = Field(default_factory=list)


class PipelineTrackingSummaryResponse(BaseModel):
    tracked_messages: int
    processed_messages: int
    skipped_messages: int
    saved_files: int
    needs_review_messages: int = 0
    needs_review_files: int = 0
    files_by_supplier: dict[str, int] = Field(default_factory=dict)
    files_by_type: dict[str, int] = Field(default_factory=dict)
    last_processed_at: str | None = None
    tracking_file: str


class PipelineReviewQueueItem(BaseModel):
    message_id: str
    sender: str
    subject: str
    processed_at: str | None = None
    attachment_name: str
    supplier: str
    document_type: str
    document_date: str | None = None
    reference: str | None = None
    amount: str | None = None
    review_reasons: list[str] = Field(default_factory=list)
    saved_path: str


class PipelineReviewQueueResponse(BaseModel):
    total: int
    files: list[PipelineReviewQueueItem] = Field(default_factory=list)
