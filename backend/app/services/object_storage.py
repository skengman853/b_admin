from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Document, User


def document_storage_backend() -> str:
    return (settings.document_storage_backend or "local").strip().lower()


def object_storage_enabled() -> bool:
    return document_storage_backend() == "s3" and bool(settings.s3_bucket)


def _storage_client():
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated at runtime
        raise RuntimeError(
            "S3 document storage requires boto3 and botocore to be installed"
        ) from exc

    config = None
    if settings.s3_force_path_style:
        config = Config(s3={"addressing_style": "path"})

    return boto3.client(
        "s3",
        region_name=settings.s3_region or None,
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
        config=config,
    )


def _normalize_local_storage_path(path: str | Path) -> str:
    path_obj = Path(path)
    if path_obj.is_absolute():
        try:
            path_obj = path_obj.relative_to(Path.cwd())
        except ValueError:
            path_obj = Path(path_obj.name)
    return path_obj.as_posix().lstrip("/")


def build_object_storage_key(*, local_path: str | Path, document_id: UUID | None = None) -> str:
    normalized = _normalize_local_storage_path(local_path)
    prefix = (settings.s3_prefix or "").strip("/")
    key = f"{prefix}/{normalized}" if prefix else normalized
    if document_id and not normalized:
        key = f"{prefix}/{document_id}" if prefix else str(document_id)
    return key


def sync_document_to_object_storage(
    *,
    document: Document,
    source_path: Path | None = None,
    force: bool = False,
) -> dict:
    if not object_storage_enabled():
        return {
            "document_id": document.id,
            "local_path": document.local_path,
            "storage_provider": document.storage_provider,
            "storage_bucket": document.storage_bucket,
            "storage_key": document.storage_key,
            "status": "skipped",
            "reason": "storage_backend_local",
        }

    if document.storage_provider == "s3" and document.storage_key and not force:
        return {
            "document_id": document.id,
            "local_path": document.local_path,
            "storage_provider": document.storage_provider,
            "storage_bucket": document.storage_bucket,
            "storage_key": document.storage_key,
            "status": "skipped",
            "reason": "already_synced",
        }

    file_path = source_path or Path(document.local_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Local file not found for storage sync: {file_path}")

    key = document.storage_key or build_object_storage_key(
        local_path=file_path,
        document_id=document.id,
    )
    client = _storage_client()
    extra_args = {"ContentType": "application/pdf"} if file_path.suffix.lower() == ".pdf" else None
    if extra_args:
        client.upload_file(str(file_path), settings.s3_bucket, key, ExtraArgs=extra_args)
    else:
        client.upload_file(str(file_path), settings.s3_bucket, key)

    document.storage_provider = "s3"
    document.storage_bucket = settings.s3_bucket
    document.storage_key = key
    document.storage_synced_at = datetime.utcnow()

    return {
        "document_id": document.id,
        "local_path": document.local_path,
        "storage_provider": document.storage_provider,
        "storage_bucket": document.storage_bucket,
        "storage_key": document.storage_key,
        "status": "synced",
        "reason": None,
    }


def ensure_local_document_file(document: Document) -> Path:
    local_path = Path(document.local_path)
    if local_path.exists() and local_path.is_file():
        return local_path

    if document.storage_provider != "s3" or not document.storage_key or not document.storage_bucket:
        raise FileNotFoundError(f"Document file not found: {document.local_path}")

    if not object_storage_enabled():
        raise FileNotFoundError(
            f"Document file not found locally and object storage is not configured: {document.local_path}"
        )

    local_path.parent.mkdir(parents=True, exist_ok=True)
    client = _storage_client()
    client.download_file(document.storage_bucket, document.storage_key, str(local_path))
    return local_path


async def sync_documents_to_object_storage(
    *,
    user: User,
    db: AsyncSession,
    limit: int,
    document_ids: list[UUID] | None = None,
    force: bool = False,
) -> dict:
    query = select(Document).where(Document.user_id == user.id, Document.derivation_index == 0)
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    elif not force:
        query = query.where(Document.storage_key.is_(None))

    result = await db.execute(query.order_by(Document.created_at.asc()).limit(limit))
    documents = list(result.scalars().all())

    synced = 0
    skipped = 0
    response_results: list[dict] = []

    for document in documents:
        try:
            item = sync_document_to_object_storage(document=document, force=force)
        except Exception as exc:
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "local_path": document.local_path,
                    "storage_provider": document.storage_provider,
                    "storage_bucket": document.storage_bucket,
                    "storage_key": document.storage_key,
                    "status": "skipped",
                    "reason": f"sync_failed:{exc.__class__.__name__}",
                }
            )
            continue

        if item["status"] == "synced":
            synced += 1
        else:
            skipped += 1
        response_results.append(item)

    await db.commit()
    return {
        "requested": len(documents),
        "synced": synced,
        "skipped": skipped,
        "results": response_results,
    }
