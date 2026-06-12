"""Set a user's password (prompts securely, hashes like the app does).

Run interactively in the api container, pointing at any database:

    docker compose exec api python scripts/set_user_password.py user@example.com 'postgresql://...'

The database URL may use postgresql:// or postgresql+asyncpg:// — the driver
prefix is normalized automatically.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def main(email: str, database_url: str) -> int:
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    password = getpass.getpass(f"new password for {email}: ")
    if len(password) < 10:
        print("refusing: use at least 10 characters", file=sys.stderr)
        return 1
    if password != getpass.getpass("repeat: "):
        print("passwords do not match", file=sys.stderr)
        return 1

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        result = await connection.execute(
            text("update users set password_hash = :hash where email = :email"),
            {"hash": pwd_context.hash(password), "email": email},
        )
    await engine.dispose()
    if result.rowcount == 0:
        print(f"no user found with email {email}", file=sys.stderr)
        return 1
    print(f"password updated for {email}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2])))
