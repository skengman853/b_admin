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
    sync_drive: bool | None = None


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
    drive_sync_requested: int = 0
    drive_sync_synced: int = 0
    drive_sync_skipped: int = 0
    deduped_documents: int = 0
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


# Documents
class DocumentResponse(BaseModel):
    id: uuid.UUID
    gmail_message_id: str
    attachment_name: str
    supplier: str
    document_type: str
    document_date: date | None
    reference: str | None
    amount: Decimal | None
    local_path: str
    needs_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    source_email_sender: str | None
    source_email_subject: str | None
    source_received_at: datetime | None
    drive_file_id: str | None
    drive_web_link: str | None
    drive_folder_path: str | None
    synced_at: datetime | None
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
    page: int
    pages: int


class DocumentDriveSyncRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    force: bool = False


class DocumentDriveSyncItem(BaseModel):
    document_id: uuid.UUID
    local_path: str
    drive_file_id: str | None = None
    drive_web_link: str | None = None
    status: str
    reason: str | None = None


class DocumentDriveSyncResponse(BaseModel):
    requested: int
    synced: int
    skipped: int
    deduped: int = 0
    results: list[DocumentDriveSyncItem] = Field(default_factory=list)
