#!/usr/bin/env python3
"""Reset an admin user's password (SQLite DB used by the app).

Interactive (default):
  docker compose exec backend python scripts/reset_admin_password.py

Non-interactive (no TTY), set env and omit prompting:
  docker compose exec -e ADMIN_NEW_PASSWORD='your-secure-password' backend \\
    python scripts/reset_admin_password.py

If several admins exist, pass --username.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

# Running as `python scripts/reset_admin_password.py` puts `scripts/` on sys.path; add app root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from passlib.context import CryptContext
from sqlalchemy import select

from app.database import async_session_factory
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _read_new_password() -> str:
    env_pw = os.environ.get("ADMIN_NEW_PASSWORD", "").strip()
    if env_pw:
        if len(env_pw) < 6:
            print("ADMIN_NEW_PASSWORD must be at least 6 characters.", file=sys.stderr)
            sys.exit(1)
        return env_pw
    a = getpass.getpass("New password: ")
    b = getpass.getpass("Confirm new password: ")
    if a != b:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(1)
    if len(a) < 6:
        print("Password must be at least 6 characters.", file=sys.stderr)
        sys.exit(1)
    return a


async def _run(username: str | None, new_password: str) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.role == "admin").order_by(User.id))
        admins = list(result.scalars().all())
        if not admins:
            print("No user with role 'admin' found.", file=sys.stderr)
            sys.exit(1)
        if username:
            target = next((u for u in admins if u.username == username), None)
            if not target:
                print(f"No admin user named {username!r}.", file=sys.stderr)
                sys.exit(1)
        elif len(admins) == 1:
            target = admins[0]
        else:
            names = ", ".join(u.username for u in admins)
            print(
                f"Multiple admins ({names}). Pass --username to choose one.",
                file=sys.stderr,
            )
            sys.exit(1)

        target.password_hash = pwd_context.hash(new_password)
        await db.commit()
        print(f"Password updated for admin {target.username!r} (id={target.id}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        help="Admin username to reset (required if more than one admin exists)",
    )
    args = parser.parse_args()
    new_password = _read_new_password()
    asyncio.run(_run(args.username, new_password))


if __name__ == "__main__":
    main()
