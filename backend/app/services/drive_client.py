from __future__ import annotations

from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GmailConnection
from app.services.drive_paths import drive_path_parts_for_local_path
from app.services.google_oauth import get_google_credentials

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


async def get_drive_service(connection: GmailConnection, db: AsyncSession):
    credentials = await get_google_credentials(connection, db)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _escape_drive_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_named_child(service, *, name: str, parent_id: str | None, mime_type: str | None = None) -> dict | None:
    query_parts = [f"name = '{_escape_drive_query_literal(name)}'", "trashed = false"]
    if parent_id:
        query_parts.append(f"'{parent_id}' in parents")
    if mime_type:
        query_parts.append(f"mimeType = '{mime_type}'")

    response = (
        service.files()
        .list(
            q=" and ".join(query_parts),
            spaces="drive",
            fields="files(id, name, mimeType, webViewLink)",
            pageSize=1,
        )
        .execute()
    )
    files = response.get("files", [])
    return files[0] if files else None


def ensure_drive_folder(service, *, name: str, parent_id: str | None = None) -> str:
    existing = _find_named_child(service, name=name, parent_id=parent_id, mime_type=FOLDER_MIME_TYPE)
    if existing:
        return existing["id"]

    metadata = {"name": name, "mimeType": FOLDER_MIME_TYPE}
    if parent_id:
        metadata["parents"] = [parent_id]

    created = service.files().create(body=metadata, fields="id").execute()
    return created["id"]


def ensure_drive_path(service, path_parts: list[str]) -> tuple[str, str]:
    parent_id: str | None = None
    normalized_parts: list[str] = []

    for part in path_parts:
        normalized_parts.append(part)
        parent_id = ensure_drive_folder(service, name=part, parent_id=parent_id)

    if parent_id is None:
        raise ValueError("Drive path must include at least one folder")

    return parent_id, "/".join(normalized_parts)


def find_existing_drive_file(service, *, filename: str, parent_id: str) -> dict | None:
    return _find_named_child(service, name=filename, parent_id=parent_id)


def upload_local_file(service, *, local_path: str, parent_id: str) -> dict:
    file_path = Path(local_path)
    existing = find_existing_drive_file(service, filename=file_path.name, parent_id=parent_id)
    if existing and existing.get("mimeType") != FOLDER_MIME_TYPE:
        return existing

    media = MediaFileUpload(file_path, mimetype="application/pdf", resumable=False)
    metadata = {"name": file_path.name, "parents": [parent_id]}
    created = (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id, name, webViewLink, parents",
        )
        .execute()
    )
    return created


def move_drive_file(
    service,
    *,
    file_id: str,
    new_name: str,
    new_parent_id: str,
) -> dict:
    current = service.files().get(fileId=file_id, fields="id, name, parents, webViewLink").execute()
    current_parents = current.get("parents", [])
    remove_parents = ",".join(parent for parent in current_parents if parent != new_parent_id)

    update_kwargs = {
        "fileId": file_id,
        "body": {"name": new_name},
        "fields": "id, name, webViewLink, parents",
    }
    if new_parent_id not in current_parents:
        update_kwargs["addParents"] = new_parent_id
    if remove_parents:
        update_kwargs["removeParents"] = remove_parents

    return service.files().update(**update_kwargs).execute()
