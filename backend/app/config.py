from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/invoice_organizer"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me-in-production"
    jwt_expiry_days: int = 7
    encryption_key: str = "change-me-in-production"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/gmail/callback"
    openai_api_key: str = ""
    s3_bucket: str = ""
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


settings = Settings()
