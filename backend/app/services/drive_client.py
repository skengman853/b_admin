from __future__ import annotations

import io
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
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
            corpora="allDrives",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        )
        .execute()
    )
    files = response.get("files", [])
    return files[0] if files else None


def find_folder_by_name(service, *, name: str, parent_id: str | None = None) -> dict | None:
    """Find a folder by name (optionally within a parent). Used to resolve the
    root invoice folder the operator names when importing from Drive."""
    return _find_named_child(service, name=name, parent_id=parent_id, mime_type=FOLDER_MIME_TYPE)


def find_folder_by_path(service, path: str) -> dict | None:
    """Resolve a slash-separated folder path, e.g.
    'Careys Bar Limited/Invoices - Careys Bar - Jack Keenan', walking each
    segment from the Drive root. Returns the leaf folder, or None if any
    segment is missing."""
    parent_id: str | None = None
    found: dict | None = None
    for segment in [p.strip() for p in path.split("/") if p.strip()]:
        found = _find_named_child(service, name=segment, parent_id=parent_id, mime_type=FOLDER_MIME_TYPE)
        if found is None:
            return None
        parent_id = found["id"]
    return found


def _list_children(service, parent_id: str) -> list[dict]:
    children: list[dict] = []
    page_token: str | None = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{parent_id}' in parents and trashed = false",
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                pageSize=1000,
                pageToken=page_token,
                corpora="allDrives",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        children.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return children


def walk_drive_folder(service, root_id: str, *, _prefix: tuple[str, ...] = ()):
    """Yield (file_dict, relative_path_parts) for every non-folder file under a
    Drive folder, recursing subfolders. relative_path_parts excludes the file
    name so callers can reconstruct '<sub>/<sub>/file.pdf'."""
    for child in _list_children(service, root_id):
        if child.get("mimeType") == FOLDER_MIME_TYPE:
            yield from walk_drive_folder(service, child["id"], _prefix=_prefix + (child["name"],))
        else:
            yield child, _prefix


def download_drive_file(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


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
