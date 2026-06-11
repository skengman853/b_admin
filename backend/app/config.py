from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: Literal["development", "production", "test"] = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/invoice_organizer"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me-in-production"
    jwt_expiry_days: int = 7
    encryption_key: str = "change-me-in-production"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/gmail/callback"
    openai_api_key: str = ""
    ai_document_extraction_enabled: bool = True
    ai_document_extraction_model: str = "gpt-4.1-mini"
    ai_document_extraction_min_confidence: float = 0.7
    ai_document_extraction_send_page_images: bool = True
    ai_document_extraction_max_image_pages: int = 8
    ai_document_extraction_image_dpi: int = 170
    ai_document_extraction_repair_enabled: bool = True
    document_storage_backend: str = "local"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = "documents"
    s3_force_path_style: bool = True
    sentry_dsn: str = ""
    frontend_url: str = "http://localhost:3000"
    documents_root: str = "Documents"
    drive_documents_root: str = "Documents"
    temp_pdfs_root: str = "temp_pdfs"
    data_root: str = "data"
    pipeline_default_days: int = 30
    pipeline_default_max_messages: int = 50
    pipeline_auto_sync_to_drive: bool = True

    class Config:
        env_file = ".env"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def frontend_origins(self) -> list[str]:
        raw = (self.frontend_url or "").strip()
        if not raw:
            return []
        return [value.strip() for value in raw.split(",") if value.strip()]


settings = Settings()


def validate_runtime_settings(current: Settings) -> list[str]:
    errors: list[str] = []
    if current.is_production:
        if current.jwt_secret == "change-me-in-production" or len(current.jwt_secret) < 24:
            errors.append("jwt_secret must be set to a strong production value")
        if current.encryption_key == "change-me-in-production" or len(current.encryption_key) < 24:
            errors.append("encryption_key must be set to a strong production value")
        if not current.frontend_origins:
            errors.append("frontend_url must define at least one allowed production origin")
        if any("localhost" in origin or "127.0.0.1" in origin for origin in current.frontend_origins):
            errors.append("frontend_url cannot point at localhost in production")
        if current.google_redirect_uri and "localhost" in current.google_redirect_uri:
            errors.append("google_redirect_uri cannot point at localhost in production")
        if current.document_storage_backend == "s3":
            if not current.s3_bucket:
                errors.append("s3_bucket is required when document_storage_backend=s3")
            if not current.s3_access_key_id:
                errors.append("s3_access_key_id is required when document_storage_backend=s3")
            if not current.s3_secret_access_key:
                errors.append("s3_secret_access_key is required when document_storage_backend=s3")
            if not current.s3_endpoint_url:
                errors.append("s3_endpoint_url is required when document_storage_backend=s3")
    return errors
