from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.local_storage import data_root


def tracking_file_path() -> Path:
    path = data_root() / "processed_emails.json"
    if not path.exists():
        path.write_text(json.dumps({"users": {}}, indent=2))
    return path


def _load_tracking() -> dict[str, Any]:
    return json.loads(tracking_file_path().read_text())


def _save_tracking(payload: dict[str, Any]) -> None:
    tracking_file_path().write_text(json.dumps(payload, indent=2, sort_keys=True))


def has_processed_message(user_id: str, message_id: str) -> bool:
    payload = _load_tracking()
    return message_id in payload.get("users", {}).get(user_id, {})


def record_processed_message(user_id: str, message_id: str, entry: dict[str, Any]) -> None:
    payload = _load_tracking()
    users = payload.setdefault("users", {})
    user_entries = users.setdefault(user_id, {})
    user_entries[message_id] = {
        **entry,
        "processed_at": entry.get("processed_at") or datetime.utcnow().isoformat(),
    }
    _save_tracking(payload)


def _user_entries(user_id: str) -> dict[str, Any]:
    payload = _load_tracking()
    return payload.get("users", {}).get(user_id, {})


def _parse_processed_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def build_tracking_summary(user_id: str) -> dict[str, Any]:
    entries = _user_entries(user_id)
    files_by_supplier: Counter[str] = Counter()
    files_by_type: Counter[str] = Counter()
    processed_messages = 0
    skipped_messages = 0
    saved_files = 0
    needs_review_messages = 0
    needs_review_files = 0
    last_processed_at: datetime | None = None

    for entry in entries.values():
        status = entry.get("status")
        if status == "processed":
            processed_messages += 1
        elif status == "skipped":
            skipped_messages += 1

        processed_at = _parse_processed_at(entry.get("processed_at"))
        if processed_at and (last_processed_at is None or processed_at > last_processed_at):
            last_processed_at = processed_at

        entry_files = entry.get("files", [])
        saved_files += len(entry_files)
        message_has_review = False
        for file_entry in entry_files:
            supplier = file_entry.get("supplier") or "Other"
            document_type = file_entry.get("document_type") or "unknown"
            files_by_supplier[supplier] += 1
            files_by_type[document_type] += 1
            if file_entry.get("needs_review"):
                needs_review_files += 1
                message_has_review = True
        if message_has_review:
            needs_review_messages += 1

    return {
        "tracked_messages": len(entries),
        "processed_messages": processed_messages,
        "skipped_messages": skipped_messages,
        "saved_files": saved_files,
        "needs_review_messages": needs_review_messages,
        "needs_review_files": needs_review_files,
        "files_by_supplier": dict(files_by_supplier),
        "files_by_type": dict(files_by_type),
        "last_processed_at": last_processed_at.isoformat() if last_processed_at else None,
        "tracking_file": str(tracking_file_path()),
    }


def build_review_queue(user_id: str) -> list[dict[str, Any]]:
    entries = _user_entries(user_id)
    review_items: list[dict[str, Any]] = []

    for message_id, entry in entries.items():
        for file_entry in entry.get("files", []):
            if not file_entry.get("needs_review"):
                continue
            review_items.append(
                {
                    "message_id": message_id,
                    "sender": entry.get("sender", ""),
                    "subject": entry.get("subject", ""),
                    "processed_at": entry.get("processed_at"),
                    "attachment_name": file_entry.get("attachment_name", ""),
                    "supplier": file_entry.get("supplier", "Other"),
                    "document_type": file_entry.get("document_type", "unknown"),
                    "document_date": file_entry.get("document_date"),
                    "reference": file_entry.get("reference"),
                    "amount": file_entry.get("amount"),
                    "review_reasons": file_entry.get("review_reasons", []),
                    "saved_path": file_entry.get("saved_path", ""),
                }
            )

    review_items.sort(key=lambda item: item.get("processed_at") or "", reverse=True)
    return review_items
