import uuid
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import String, Boolean, Float, Text, Date, DateTime, ForeignKey, Index, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    gmail_connection: Mapped["GmailConnection | None"] = relationship(back_populates="user", uselist=False)
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="user")
    documents: Mapped[list["Document"]] = relationship(back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
    transaction_document_links: Mapped[list["TransactionDocumentLink"]] = relationship(back_populates="user")
    transaction_review_events: Mapped[list["TransactionReviewEvent"]] = relationship(back_populates="user")
    transaction_rules: Mapped[list["TransactionRule"]] = relationship(back_populates="user")
    document_extraction_runs: Mapped[list["DocumentExtractionRun"]] = relationship(back_populates="user")
    document_financial_facts: Mapped[list["DocumentFinancialFact"]] = relationship(back_populates="user")
    document_financial_rows: Mapped[list["DocumentFinancialRow"]] = relationship(back_populates="user")
    reconciliation_suggestions: Mapped[list["ReconciliationSuggestion"]] = relationship(back_populates="user")
    reconciliation_suggestion_items: Mapped[list["ReconciliationSuggestionItem"]] = relationship(back_populates="user")


class GmailConnection(Base):
    __tablename__ = "gmail_connections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    gmail_email: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime)
    history_id: Mapped[str | None] = mapped_column(String(50))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="gmail_connection")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_invoices_user_status", "user_id", "status"),
        Index("idx_invoices_user_date", "user_id", "invoice_date"),
        Index("idx_invoices_document_id", "document_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column()
    vat_amount: Mapped[Decimal | None] = mapped_column()
    currency: Mapped[str | None] = mapped_column(String(3), default="GBP")
    invoice_date: Mapped[date | None] = mapped_column(Date)
    source_email_id: Mapped[str | None] = mapped_column(String(255))
    source_email_subject: Mapped[str | None] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="invoices")
    document: Mapped["Document | None"] = relationship("Document", back_populates="invoice")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_lookup", "user_id", "gmail_message_id", "attachment_index", "derivation_index", unique=True),
        Index("idx_documents_user_created", "user_id", "created_at"),
        Index("idx_documents_user_synced", "user_id", "synced_at"),
        Index("idx_documents_user_review", "user_id", "needs_review"),
        Index("idx_documents_parent", "parent_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    attachment_index: Mapped[int] = mapped_column(default=0)
    derivation_index: Mapped[int] = mapped_column(default=0)
    attachment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier: Mapped[str] = mapped_column(String(255), nullable=False, default="Other")
    document_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    document_date: Mapped[date | None] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column()
    vat_amount: Mapped[Decimal | None] = mapped_column()
    currency: Mapped[str | None] = mapped_column(String(3))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime)
    ai_extraction_status: Mapped[str | None] = mapped_column(String(20))
    ai_extraction_provider: Mapped[str | None] = mapped_column(String(50))
    ai_extraction_model: Mapped[str | None] = mapped_column(String(100))
    ai_extraction_payload: Mapped[dict | None] = mapped_column(JSON)
    ai_extracted_at: Mapped[datetime | None] = mapped_column(DateTime)
    storage_provider: Mapped[str | None] = mapped_column(String(20))
    storage_bucket: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(Text)
    storage_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_email_sender: Mapped[str | None] = mapped_column(Text)
    source_email_subject: Mapped[str | None] = mapped_column(Text)
    source_received_at: Mapped[datetime | None] = mapped_column(DateTime)
    drive_file_id: Mapped[str | None] = mapped_column(String(255))
    drive_web_link: Mapped[str | None] = mapped_column(Text)
    drive_folder_path: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="documents")
    parent_document: Mapped["Document | None"] = relationship(
        "Document",
        remote_side="Document.id",
        back_populates="child_documents",
    )
    child_documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="parent_document",
        cascade="all, delete-orphan",
    )
    invoice: Mapped["Invoice | None"] = relationship(
        "Invoice",
        back_populates="document",
        uselist=False,
    )
    transaction_document_links: Mapped[list["TransactionDocumentLink"]] = relationship(
        "TransactionDocumentLink",
        back_populates="document",
    )
    extraction_runs: Mapped[list["DocumentExtractionRun"]] = relationship(
        "DocumentExtractionRun",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    financial_fact: Mapped["DocumentFinancialFact | None"] = relationship(
        "DocumentFinancialFact",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )
    financial_rows: Mapped[list["DocumentFinancialRow"]] = relationship(
        "DocumentFinancialRow",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    reconciliation_suggestion_items: Mapped[list["ReconciliationSuggestionItem"]] = relationship(
        "ReconciliationSuggestionItem",
        back_populates="document",
    )


class DocumentExtractionRun(Base):
    __tablename__ = "document_extraction_runs"
    __table_args__ = (
        Index("idx_document_extraction_runs_document", "document_id", "created_at"),
        Index("idx_document_extraction_runs_user", "user_id", "created_at"),
        Index("idx_document_extraction_runs_status", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    extractor_family: Mapped[str] = mapped_column(String(50), nullable=False)
    extractor_profile: Mapped[str | None] = mapped_column(String(100))
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="rules")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    review_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="document_extraction_runs")
    document: Mapped["Document"] = relationship(back_populates="extraction_runs")
    financial_facts: Mapped[list["DocumentFinancialFact"]] = relationship(back_populates="extraction_run")
    financial_rows: Mapped[list["DocumentFinancialRow"]] = relationship(back_populates="extraction_run")


class DocumentFinancialFact(Base):
    __tablename__ = "document_financial_facts"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_document_financial_facts_document"),
        Index("idx_document_financial_facts_user_type_date", "user_id", "document_type", "document_date"),
        Index("idx_document_financial_facts_supplier_date", "supplier_canonical", "document_date"),
        Index("idx_document_financial_facts_run", "extraction_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extraction_runs.id", ondelete="SET NULL")
    )
    supplier_canonical: Mapped[str] = mapped_column(String(255), nullable=False)
    pub_hint: Mapped[str | None] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    statement_kind: Mapped[str | None] = mapped_column(String(100))
    reference: Mapped[str | None] = mapped_column(String(255))
    document_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column()
    vat_amount: Mapped[Decimal | None] = mapped_column()
    currency: Mapped[str | None] = mapped_column(String(3))
    account_number: Mapped[str | None] = mapped_column(String(255))
    account_name: Mapped[str | None] = mapped_column(String(255))
    is_financial: Mapped[bool] = mapped_column(Boolean, default=True)
    is_primary_version: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="document_financial_facts")
    document: Mapped["Document"] = relationship(back_populates="financial_fact")
    extraction_run: Mapped["DocumentExtractionRun | None"] = relationship(back_populates="financial_facts")


class DocumentFinancialRow(Base):
    __tablename__ = "document_financial_rows"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "row_index", name="uq_document_financial_rows_run_row"),
        Index("idx_document_financial_rows_document", "document_id", "row_index"),
        Index("idx_document_financial_rows_run", "extraction_run_id", "row_index"),
        Index("idx_document_financial_rows_reference", "reference"),
        Index("idx_document_financial_rows_clearing_reference", "clearing_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_extraction_runs.id", ondelete="CASCADE"))
    row_index: Mapped[int] = mapped_column(nullable=False)
    row_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255))
    clearing_reference: Mapped[str | None] = mapped_column(String(255))
    event_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column()
    signed_amount: Mapped[Decimal | None] = mapped_column()
    currency: Mapped[str | None] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    is_financial: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="document_financial_rows")
    document: Mapped["Document"] = relationship(back_populates="financial_rows")
    extraction_run: Mapped["DocumentExtractionRun"] = relationship(back_populates="financial_rows")
    reconciliation_suggestion_items: Mapped[list["ReconciliationSuggestionItem"]] = relationship(
        "ReconciliationSuggestionItem",
        back_populates="financial_row",
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("idx_transactions_user_date", "user_id", "transaction_date"),
        Index("idx_transactions_user_source_date", "user_id", "source_type", "transaction_date"),
        Index("idx_transactions_user_pub_date", "user_id", "pub", "transaction_date"),
        Index("idx_transactions_source_row", "user_id", "source_file", "source_sheet", "row_number", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(50), default="vatbook")
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    source_sheet: Mapped[str] = mapped_column(String(255), nullable=False)
    row_number: Mapped[int] = mapped_column(nullable=False)
    posted_account: Mapped[str | None] = mapped_column(String(255))
    pub: Mapped[str | None] = mapped_column(String(255))
    transaction_date: Mapped[date | None] = mapped_column(Date)
    description1: Mapped[str | None] = mapped_column(Text)
    description2: Mapped[str | None] = mapped_column(Text)
    debit_amount: Mapped[Decimal | None] = mapped_column()
    credit_amount: Mapped[Decimal | None] = mapped_column()
    transaction_type: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(255))
    resale_23_amount: Mapped[Decimal | None] = mapped_column()
    non_resale_23_amount: Mapped[Decimal | None] = mapped_column()
    non_resale_13_5_amount: Mapped[Decimal | None] = mapped_column()
    non_resale_9_amount: Mapped[Decimal | None] = mapped_column()
    non_resale_0_amount: Mapped[Decimal | None] = mapped_column()
    annotation_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    annotation_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    has_linked_annotation: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    review_note: Mapped[str | None] = mapped_column(Text)
    expected_supplier: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_row_json: Mapped[dict] = mapped_column(JSON, default=dict)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="transactions")
    document_links: Mapped[list["TransactionDocumentLink"]] = relationship(
        "TransactionDocumentLink",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
    review_events: Mapped[list["TransactionReviewEvent"]] = relationship(
        "TransactionReviewEvent",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
    reconciliation_suggestions: Mapped[list["ReconciliationSuggestion"]] = relationship(
        "ReconciliationSuggestion",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )


class ReconciliationSuggestion(Base):
    __tablename__ = "reconciliation_suggestions"
    __table_args__ = (
        Index("idx_reconciliation_suggestions_transaction", "transaction_id", "status", "created_at"),
        Index("idx_reconciliation_suggestions_user", "user_id", "status", "created_at"),
        Index("idx_reconciliation_suggestions_type", "suggestion_type", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    suggestion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="suggested")
    confidence_score: Mapped[float | None] = mapped_column(Float)
    reason_summary: Mapped[str | None] = mapped_column(Text)
    reason_json: Mapped[dict] = mapped_column(JSON, default=dict)
    verifier_status: Mapped[str | None] = mapped_column(String(20))
    extractor_version: Mapped[str | None] = mapped_column(String(50))
    matcher_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="reconciliation_suggestions")
    transaction: Mapped["Transaction"] = relationship(back_populates="reconciliation_suggestions")
    items: Mapped[list["ReconciliationSuggestionItem"]] = relationship(
        "ReconciliationSuggestionItem",
        back_populates="suggestion",
        cascade="all, delete-orphan",
    )


class ReconciliationSuggestionItem(Base):
    __tablename__ = "reconciliation_suggestion_items"
    __table_args__ = (
        Index("idx_reconciliation_suggestion_items_suggestion", "suggestion_id", "item_role"),
        Index("idx_reconciliation_suggestion_items_document", "document_id"),
        Index("idx_reconciliation_suggestion_items_financial_row", "financial_row_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    suggestion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reconciliation_suggestions.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    financial_row_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_financial_rows.id", ondelete="SET NULL")
    )
    item_role: Mapped[str] = mapped_column(String(50), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column()
    signed_amount: Mapped[Decimal | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="reconciliation_suggestion_items")
    suggestion: Mapped["ReconciliationSuggestion"] = relationship(back_populates="items")
    document: Mapped["Document | None"] = relationship(back_populates="reconciliation_suggestion_items")
    financial_row: Mapped["DocumentFinancialRow | None"] = relationship(back_populates="reconciliation_suggestion_items")


class TransactionDocumentLink(Base):
    __tablename__ = "transaction_document_links"
    __table_args__ = (
        Index("idx_transaction_document_links_transaction", "transaction_id"),
        Index("idx_transaction_document_links_document", "document_id"),
        Index("idx_transaction_document_links_status", "user_id", "status"),
        UniqueConstraint("transaction_id", "document_id", "role", name="uq_transaction_document_link"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(50), default="invoice")
    status: Mapped[str] = mapped_column(String(20), default="suggested")
    score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(20))
    match_reason: Mapped[str | None] = mapped_column(Text)
    amount_applied: Mapped[Decimal | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="transaction_document_links")
    transaction: Mapped["Transaction"] = relationship(back_populates="document_links")
    document: Mapped["Document"] = relationship(back_populates="transaction_document_links")


class TransactionReviewEvent(Base):
    __tablename__ = "transaction_review_events"
    __table_args__ = (
        Index("idx_transaction_review_events_transaction", "transaction_id", "created_at"),
        Index("idx_transaction_review_events_user", "user_id", "created_at"),
        Index("idx_transaction_review_events_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_email: Mapped[str | None] = mapped_column(String(255))
    previous_review_status: Mapped[str | None] = mapped_column(String(32))
    current_review_status: Mapped[str | None] = mapped_column(String(32))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    link_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transaction_document_links.id", ondelete="SET NULL"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="transaction_review_events")
    transaction: Mapped["Transaction"] = relationship(back_populates="review_events")


class TransactionRule(Base):
    __tablename__ = "transaction_rules"
    __table_args__ = (
        Index("idx_transaction_rules_user_active", "user_id", "is_active"),
        Index("idx_transaction_rules_lookup", "user_id", "source_type", "pub", "match_field", "match_value"),
        UniqueConstraint(
            "user_id",
            "source_type",
            "pub",
            "match_field",
            "match_value",
            name="uq_transaction_rule_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(50), default="bank_statement")
    pub: Mapped[str | None] = mapped_column(String(255))
    match_field: Mapped[str] = mapped_column(String(50), default="description1_counterparty")
    match_value: Mapped[str] = mapped_column(String(255), nullable=False)
    display_label: Mapped[str | None] = mapped_column(String(255))
    category_override: Mapped[str | None] = mapped_column(String(255))
    review_status: Mapped[str] = mapped_column(String(32), default="handled_by_rule")
    expected_supplier: Mapped[str | None] = mapped_column(String(255))
    document_expectation: Mapped[str | None] = mapped_column(String(50))
    owner_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="transaction_rules")


class ProcessedEmail(Base):
    __tablename__ = "processed_emails"
    __table_args__ = (
        Index("idx_processed_emails_lookup", "user_id", "gmail_message_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    is_invoice: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
