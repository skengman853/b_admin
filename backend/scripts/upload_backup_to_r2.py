"""Upload a database backup file to the configured R2/S3 bucket.

Run inside the api container:
    python scripts/upload_backup_to_r2.py backups/b_admin-20260612T120000.dump

Uploads to <s3_prefix>/backups/db/<filename> and prunes old backups beyond
KEEP_REMOTE most recent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.object_storage import _storage_client, object_storage_enabled

KEEP_REMOTE = 14


def backup_key_prefix() -> str:
    prefix = (settings.s3_prefix or "").strip("/")
    return f"{prefix}/backups/db/" if prefix else "backups/db/"


def main(path_str: str) -> int:
    if not object_storage_enabled():
        print("object storage is not configured; refusing to skip backup silently", file=sys.stderr)
        return 1

    path = Path(path_str)
    if not path.exists():
        print(f"backup file not found: {path}", file=sys.stderr)
        return 1

    client = _storage_client()
    key = backup_key_prefix() + path.name
    client.upload_file(str(path), settings.s3_bucket, key)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"uploaded {path.name} ({size_mb:.1f} MB) -> s3://{settings.s3_bucket}/{key}")

    listing = client.list_objects_v2(Bucket=settings.s3_bucket, Prefix=backup_key_prefix())
    objects = sorted(listing.get("Contents", []), key=lambda obj: obj["Key"])
    for stale in objects[:-KEEP_REMOTE]:
        client.delete_object(Bucket=settings.s3_bucket, Key=stale["Key"])
        print(f"pruned old backup {stale['Key']}")
    print(f"remote backups retained: {min(len(objects), KEEP_REMOTE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
