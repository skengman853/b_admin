import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
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
    document_id: uuid.UUID | None
    supplier_name: str | None
    reference: str | None
    amount: Decimal | None
    vat_amount: Decimal | None
    currency: str | None
    invoice_date: date | None
    confidence_score: float | None
    status: str
    source_email_subject: str | None
    created_at: datetime


class InvoiceUpdateRequest(BaseModel):
    supplier_name: str | None = None
    reference: str | None = None
    amount: Decimal | None = None
    vat_amount: Decimal | None = None
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


class SupplierDocumentInventoryItemResponse(BaseModel):
    id: uuid.UUID
    supplier: str
    canonical_supplier: str | None = None
    document_type: str
    document_date: date | None
    reference: str | None
    amount: Decimal | None
    extraction_status: str
    needs_review: bool
    attachment_name: str
    storage_state: str = "local_only"
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    local_path: str
    drive_file_id: str | None = None
    drive_web_link: str | None = None
    drive_folder_path: str | None = None
    source_email_subject: str | None = None
    pub_hint: str | None = None


class SupplierDocumentInventoryResponse(BaseModel):
    supplier_query: str
    canonical_supplier: str | None = None
    month: str | None = None
    selected_months: list[str] = Field(default_factory=list)
    window_months: int = 1
    total_documents: int = 0
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    counts_by_storage: dict[str, int] = Field(default_factory=dict)
    available_months: list[str] = Field(default_factory=list)
    documents: list[SupplierDocumentInventoryItemResponse] = Field(default_factory=list)


class SupplierOptionResponse(BaseModel):
    supplier: str
    canonical_supplier: str | None = None
    document_count: int = 0


class SupplierOptionsResponse(BaseModel):
    suppliers: list[SupplierOptionResponse] = Field(default_factory=list)


class DocumentStorageSummaryResponse(BaseModel):
    month: str | None = None
    selected_months: list[str] = Field(default_factory=list)
    window_months: int = 1
    pub: str | None = None
    total_documents: int = 0
    local_only: int = 0
    r2_only: int = 0
    drive_only: int = 0
    r2_and_drive: int = 0


class StatementWorkbenchSettlementComponentResponse(BaseModel):
    entry_kind: str
    reference: str | None = None
    related_reference: str | None = None
    event_date: date | None = None
    due_date: date | None = None
    amount: Decimal | None = None


class StatementWorkbenchSettlementResponse(BaseModel):
    payment_reference: str | None = None
    payment_date: date | None = None
    due_date: date | None = None
    amount: Decimal | None = None
    net_amount: Decimal | None = None
    component_count: int = 0
    components: list[StatementWorkbenchSettlementComponentResponse] = Field(default_factory=list)


class StatementWorkbenchTransactionResponse(BaseModel):
    id: uuid.UUID
    row_number: int
    transaction_date: date | None = None
    description1: str | None = None
    pub: str | None = None
    debit_amount: Decimal | None = None
    credit_amount: Decimal | None = None
    review_status: str
    reason: str


class StatementWorkbenchItemResponse(BaseModel):
    id: uuid.UUID
    supplier: str
    canonical_supplier: str | None = None
    statement_kind: str | None = None
    document_date: date | None = None
    reference: str | None = None
    amount: Decimal | None = None
    account_number: str | None = None
    account_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    note: str | None = None
    invoice_refs: list[str] = Field(default_factory=list)
    credit_refs: list[str] = Field(default_factory=list)
    payment_refs: list[str] = Field(default_factory=list)
    imported_invoice_refs: list[str] = Field(default_factory=list)
    missing_invoice_refs: list[str] = Field(default_factory=list)
    imported_credit_refs: list[str] = Field(default_factory=list)
    missing_credit_refs: list[str] = Field(default_factory=list)
    settlement_count: int = 0
    settlements: list[StatementWorkbenchSettlementResponse] = Field(default_factory=list)
    likely_transactions: list[StatementWorkbenchTransactionResponse] = Field(default_factory=list)
    storage_state: str = "local_only"
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    drive_file_id: str | None = None
    drive_web_link: str | None = None
    pub_hint: str | None = None


class StatementWorkbenchResponse(BaseModel):
    supplier_query: str
    canonical_supplier: str | None = None
    month: str | None = None
    selected_months: list[str] = Field(default_factory=list)
    window_months: int = 1
    pub: str | None = None
    total_statements: int = 0
    statements_with_settlements: int = 0
    total_missing_invoice_refs: int = 0
    total_missing_credit_refs: int = 0
    total_likely_transactions: int = 0
    statements: list[StatementWorkbenchItemResponse] = Field(default_factory=list)


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
    parent_document_id: uuid.UUID | None
    gmail_message_id: str
    attachment_name: str
    derivation_index: int
    supplier: str
    document_type: str
    document_date: date | None
    reference: str | None
    amount: Decimal | None
    vat_amount: Decimal | None
    currency: str | None
    confidence_score: float | None
    extraction_status: str
    extracted_at: datetime | None
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    storage_synced_at: datetime | None = None
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


class DocumentExtractionCandidateResponse(BaseModel):
    reference: str | None
    document_date: date | None
    amount: Decimal | None
    vat_amount: Decimal | None
    currency: str | None


class DocumentStatementEntryResponse(BaseModel):
    event_date: date | None = None
    reference: str | None = None
    transaction_type: str | None = None
    due_date: date | None = None
    clearing_reference: str | None = None
    amount: Decimal | None = None
    raw_text: str | None = None


class DocumentStatementAnalysisResponse(BaseModel):
    statement_kind: str
    is_financial: bool
    account_number: str | None = None
    account_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    total_due: Decimal | None = None
    settlement_discount_total: Decimal | None = None
    closing_balance: Decimal | None = None
    invoice_references: list[str] = Field(default_factory=list)
    payment_references: list[str] = Field(default_factory=list)
    note: str | None = None
    entries: list[DocumentStatementEntryResponse] = Field(default_factory=list)


class DocumentLedgerEntryResponse(BaseModel):
    document_id: uuid.UUID
    document_type: str
    supplier: str
    entry_kind: str
    event_date: date | None = None
    due_date: date | None = None
    reference: str | None = None
    related_reference: str | None = None
    amount: Decimal | None = None
    signed_amount: Decimal | None = None
    vat_amount: Decimal | None = None
    currency: str | None = None
    is_financial: bool = True
    statement_kind: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    raw_text: str | None = None


class DocumentLedgerSettlementResponse(BaseModel):
    payment_entry: DocumentLedgerEntryResponse
    component_entries: list[DocumentLedgerEntryResponse] = Field(default_factory=list)
    net_amount: Decimal | None = None


class DocumentLedgerAnalysisResponse(BaseModel):
    document_id: uuid.UUID
    supplier: str
    document_type: str
    is_financial: bool
    statement_kind: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    note: str | None = None
    entries: list[DocumentLedgerEntryResponse] = Field(default_factory=list)
    settlements: list[DocumentLedgerSettlementResponse] = Field(default_factory=list)


class DocumentDetailResponse(DocumentResponse):
    extracted_text: str | None = None
    extraction_candidates: list[DocumentExtractionCandidateResponse] = Field(default_factory=list)
    statement_analysis: DocumentStatementAnalysisResponse | None = None
    ledger_analysis: DocumentLedgerAnalysisResponse | None = None
    parent_document: DocumentResponse | None = None
    child_documents: list[DocumentResponse] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
    page: int
    pages: int


class DocumentUpdateRequest(BaseModel):
    supplier: str | None = None
    document_type: str | None = None
    document_date: date | None = None
    reference: str | None = None
    amount: Decimal | None = None
    vat_amount: Decimal | None = None
    currency: str | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    extraction_status: str | None = None
    needs_review: bool | None = None
    review_reasons: list[str] | None = None
    mark_reviewed: bool = False


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


class DocumentStorageSyncRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    force: bool = False


class DocumentStorageSyncItem(BaseModel):
    document_id: uuid.UUID
    local_path: str
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    status: str
    reason: str | None = None


class DocumentStorageSyncResponse(BaseModel):
    requested: int
    synced: int
    skipped: int
    results: list[DocumentStorageSyncItem] = Field(default_factory=list)


class DocumentExtractionRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    force: bool = False


class DocumentExtractionItem(BaseModel):
    document_id: uuid.UUID
    status: str
    reason: str | None = None
    document_type: str
    supplier: str
    amount: str | None = None
    vat_amount: str | None = None
    confidence_score: float | None = None


class DocumentExtractionResponse(BaseModel):
    requested: int
    extracted: int
    skipped: int
    results: list[DocumentExtractionItem] = Field(default_factory=list)


class LocalDocumentImportRequest(BaseModel):
    source_path: str
    limit: int = Field(default=250, ge=1, le=2000)
    supplier_filters: list[str] = Field(default_factory=list)
    document_types: list[Literal["invoice", "statement", "credit_note", "receipt", "unknown"]] = Field(
        default_factory=list
    )
    pub_filters: list[str] = Field(default_factory=list)
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    include_archives: bool = False
    recurse: bool = True
    extract_after_import: bool = True


class LocalDocumentImportItem(BaseModel):
    relative_path: str
    supplier: str | None = None
    document_type: str | None = None
    pub_hint: str | None = None
    status: str
    reason: str | None = None
    saved_path: str | None = None
    document_id: uuid.UUID | None = None


class LocalDocumentImportResponse(BaseModel):
    source_path: str
    scanned_files: int
    eligible_files: int
    imported_documents: int
    extracted_documents: int
    skipped_files: int
    results: list[LocalDocumentImportItem] = Field(default_factory=list)


class StatementContextImportRequest(BaseModel):
    source_path: str
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    source_type: Literal["bank_statement", "vatbook"] = "bank_statement"
    pub: str | None = None
    supplier_filters: list[str] = Field(default_factory=list)
    adjacent_months: int = Field(default=1, ge=0, le=3)
    limit: int = Field(default=250, ge=1, le=2000)
    recurse: bool = True
    extract_after_import: bool = True


class StatementContextImportResponse(BaseModel):
    source_path: str
    month: str
    months_considered: list[str] = Field(default_factory=list)
    source_type: str
    suppliers_considered: list[str] = Field(default_factory=list)
    pubs_considered: list[str] = Field(default_factory=list)
    scanned_files: int
    eligible_files: int
    imported_documents: int
    extracted_documents: int
    skipped_files: int
    results: list[LocalDocumentImportItem] = Field(default_factory=list)


class DocumentSplitResponse(BaseModel):
    parent_document: DocumentDetailResponse
    child_documents: list[DocumentDetailResponse] = Field(default_factory=list)
    created: int
    updated: int
    deleted: int = 0


# Transactions
class TransactionImportRequest(BaseModel):
    source_type: Literal["vatbook", "bank_statement"] = "vatbook"
    workbook_path: str | None = None
    statement_path: str | None = None
    sheet_name: str | None = None
    replace_existing: bool = True


class TransactionImportResponse(BaseModel):
    source_type: str
    source_file: str
    source_name: str | None = None
    workbook_path: str | None = None
    statement_path: str | None = None
    sheet_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    provider: str | None = None
    imported_transactions: int
    replaced_transactions: int
    skipped_transactions: int
    annotation_count: int
    first_transaction_date: date | None = None
    last_transaction_date: date | None = None
    pubs: list[str] = Field(default_factory=list)


class TransactionResponse(BaseModel):
    id: uuid.UUID
    source_type: str
    source_file: str
    source_sheet: str
    row_number: int
    posted_account: str | None
    pub: str | None
    transaction_date: date | None
    description1: str | None
    description2: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    transaction_type: str | None
    category: str | None
    resale_23_amount: Decimal | None
    non_resale_23_amount: Decimal | None
    non_resale_13_5_amount: Decimal | None
    non_resale_9_amount: Decimal | None
    non_resale_0_amount: Decimal | None
    annotation_types: list[str] = Field(default_factory=list)
    annotation_notes: list[str] = Field(default_factory=list)
    has_linked_annotation: bool
    review_status: str
    review_note: str | None
    expected_supplier: str | None
    reviewed_at: datetime | None
    imported_at: datetime


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    page: int
    pages: int


class TransactionDocumentMatchResponse(BaseModel):
    document_id: uuid.UUID
    document_type: str
    supplier: str
    reference: str | None
    document_date: date | None
    amount: Decimal | None
    vat_amount: Decimal | None
    storage_state: str = "local_only"
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    drive_file_id: str | None = None
    drive_web_link: str | None = None
    score: float | None
    reason: str


class TransactionFlowDocumentResponse(BaseModel):
    document_id: uuid.UUID
    supplier: str
    document_type: str
    reference: str | None = None
    document_date: date | None = None
    amount: Decimal | None = None
    vat_amount: Decimal | None = None
    score: float | None = None
    role: str | None = None
    reason: str | None = None
    storage_state: str = "local_only"
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    drive_file_id: str | None = None
    drive_web_link: str | None = None
    statement_kind: str | None = None
    is_financial: bool | None = None
    invoice_reference_count: int = 0
    payment_reference_count: int = 0
    credit_reference_count: int = 0
    settlement_count: int = 0


class TransactionFlowSettlementResponse(BaseModel):
    source_document_id: uuid.UUID
    source_supplier: str
    source_reference: str | None = None
    source_document_date: date | None = None
    statement_kind: str | None = None
    payment_entry: DocumentLedgerEntryResponse
    component_entries: list[DocumentLedgerEntryResponse] = Field(default_factory=list)
    net_amount: Decimal | None = None
    matches_transaction_amount: bool = False


class TransactionFlowStageResponse(BaseModel):
    key: str
    title: str
    status: str
    summary: str
    items: list[str] = Field(default_factory=list)
    documents: list[TransactionFlowDocumentResponse] = Field(default_factory=list)


class TransactionFlowResponse(BaseModel):
    flow_type: str
    supplier_label: str | None = None
    bank_counterparty: str | None = None
    next_step: str
    stages: list[TransactionFlowStageResponse] = Field(default_factory=list)
    settlements: list[TransactionFlowSettlementResponse] = Field(default_factory=list)


class TransactionReconciliationItemResponse(BaseModel):
    transaction_id: uuid.UUID
    source_type: str
    row_number: int
    pub: str | None
    transaction_date: date | None
    description1: str | None
    description2: str | None
    category: str | None
    transaction_type: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    annotation_types: list[str] = Field(default_factory=list)
    annotation_notes: list[str] = Field(default_factory=list)
    has_linked_annotation: bool
    status: str
    analysis_note: str | None = None
    resolution_bucket: str
    recommended_review_status: str | None = None
    resolution_reason: str | None = None
    exact_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    suggested_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    supporting_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)


class TransactionReconciliationReportResponse(BaseModel):
    month: str
    pub: str | None
    total_transactions: int
    expense_transactions: int
    annotated_transactions: int
    linked_transactions: int
    matched_transactions: int
    partial_transactions: int = 0
    suggested_transactions: int
    unmatched_transactions: int
    invoice_documents_in_month: int
    unmatched_invoice_documents: int
    resolution_bucket_counts: dict[str, int] = Field(default_factory=dict)
    transactions: list[TransactionReconciliationItemResponse] = Field(default_factory=list)
    unmatched_documents: list[TransactionDocumentMatchResponse] = Field(default_factory=list)


class TransactionLinkedDocumentResponse(BaseModel):
    id: uuid.UUID
    supplier: str
    document_type: str
    reference: str | None
    document_date: date | None
    amount: Decimal | None
    vat_amount: Decimal | None
    storage_state: str = "local_only"
    storage_provider: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    drive_file_id: str | None = None
    drive_web_link: str | None = None
    local_path: str
    needs_review: bool


class TransactionLinkResponse(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    document_id: uuid.UUID
    role: str
    status: str
    score: float | None
    confidence: str | None
    match_reason: str | None
    amount_applied: Decimal | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    document: TransactionLinkedDocumentResponse


class TransactionReviewEventResponse(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    event_type: str
    actor_email: str | None
    previous_review_status: str | None
    current_review_status: str | None
    document_id: uuid.UUID | None
    link_id: uuid.UUID | None
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class TransactionLinksResponse(BaseModel):
    transaction: TransactionResponse
    status: str
    analysis_note: str | None = None
    resolution_bucket: str
    recommended_review_status: str | None = None
    resolution_reason: str | None = None
    persisted_links: list[TransactionLinkResponse] = Field(default_factory=list)
    exact_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    suggested_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    supporting_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)


class TransactionDetailResponse(BaseModel):
    transaction: TransactionResponse
    status: str
    analysis_note: str | None = None
    resolution_bucket: str
    recommended_review_status: str | None = None
    resolution_reason: str | None = None
    reconciliation_flow: TransactionFlowResponse | None = None
    history_count: int = 0
    persisted_links: list[TransactionLinkResponse] = Field(default_factory=list)
    exact_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    suggested_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    supporting_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)


class TransactionHistoryResponse(BaseModel):
    transaction_id: uuid.UUID
    events: list[TransactionReviewEventResponse] = Field(default_factory=list)


class TransactionReviewQueueItemResponse(BaseModel):
    transaction: TransactionResponse
    status: str
    needs_action: bool = True
    analysis_note: str | None = None
    resolution_bucket: str
    recommended_review_status: str | None = None
    resolution_reason: str | None = None
    persisted_links: list[TransactionLinkResponse] = Field(default_factory=list)
    exact_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    suggested_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)
    supporting_matches: list[TransactionDocumentMatchResponse] = Field(default_factory=list)


class TransactionReviewQueueResponse(BaseModel):
    month: str
    selected_months: list[str] = Field(default_factory=list)
    window_months: int = 0
    pub: str | None
    annotated_only: bool
    statuses: list[str] = Field(default_factory=list)
    total: int
    page: int
    pages: int
    matched_transactions: int
    partial_transactions: int
    suggested_transactions: int
    unmatched_transactions: int
    resolution_bucket_counts: dict[str, int] = Field(default_factory=dict)
    transactions: list[TransactionReviewQueueItemResponse] = Field(default_factory=list)


class TransactionReviewUpdateRequest(BaseModel):
    review_status: Literal[
        "pending",
        "linked",
        "supporting_docs_only",
        "hard_copy_available",
        "awaiting_document",
        "no_document_expected",
    ]
    category: str | None = None
    review_note: str | None = None
    expected_supplier: str | None = None


class TransactionRuleResponse(BaseModel):
    id: uuid.UUID
    source_type: str
    pub: str | None
    match_field: str
    match_value: str
    display_label: str | None
    category_override: str | None
    review_status: str
    expected_supplier: str | None
    document_expectation: str | None
    owner_note: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TransactionRuleCreateRequest(BaseModel):
    category_override: str
    review_status: Literal[
        "handled_by_rule",
        "no_document_expected",
        "hard_copy_available",
    ] = "handled_by_rule"
    document_expectation: Literal[
        "none",
        "hard_copy",
        "annual_invoice",
        "monthly_invoice",
        "statement",
        "unknown",
    ] = "unknown"
    owner_note: str | None = None
    expected_supplier: str | None = None
    apply_same_pub_only: bool = True
    apply_to_existing: bool = True


class TransactionRuleCreateResponse(BaseModel):
    transaction: TransactionResponse
    rule: TransactionRuleResponse
    updated_transactions: int


class TransactionRuleListResponse(BaseModel):
    rules: list[TransactionRuleResponse] = Field(default_factory=list)


class TransactionRuleApplyRequest(BaseModel):
    rule_id: uuid.UUID


class TransactionRuleApplyResponse(BaseModel):
    transaction: TransactionResponse
    rule: TransactionRuleResponse


class TransactionLinkCreateRequest(BaseModel):
    document_id: uuid.UUID
    role: str = "invoice"
    status: str = "confirmed"
    score: float | None = None
    confidence: str | None = None
    match_reason: str | None = None
    amount_applied: Decimal | None = None
    note: str | None = None


class TransactionLinkUpdateRequest(BaseModel):
    role: str | None = None
    status: str | None = None
    score: float | None = None
    confidence: str | None = None
    match_reason: str | None = None
    amount_applied: Decimal | None = None
    note: str | None = None
