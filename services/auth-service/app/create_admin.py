import argparse
import asyncio
import getpass
import os
import sys
from uuid import UUID

import asyncpg
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas.auth import RegisterRequest
from app.security import hash_password


async def create_admin(settings: Settings, *, email: str, password: str) -> UUID:
    # Same email/password rules as the public register endpoint.
    credentials = RegisterRequest(email=email, password=password)
    password_hash = await hash_password(credentials.password, settings.bcrypt_rounds)
    conn = await asyncpg.connect(settings.database_url)
    try:
        # If the email already exists the user is promoted and the old password is kept.
        return await conn.fetchval(
            """
            INSERT INTO users (email, password_hash, role)
            VALUES ($1, $2, 'admin')
            ON CONFLICT (email) DO UPDATE SET role = 'admin'
            RETURNING id
            """,
            credentials.email,
            password_hash,
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote an admin user")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    try:
        user_id = asyncio.run(create_admin(get_settings(), email=args.email, password=password))
    except ValidationError as exc:
        sys.exit(f"Invalid input: {exc}")
    print(f"Admin ready: {user_id}")


if __name__ == "__main__":
    main()
