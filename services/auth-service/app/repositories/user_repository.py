import uuid

import asyncpg

from app.db import Executor


async def create_user(
    db: Executor, *, email: str, password_hash: str, role: str = "user"
) -> asyncpg.Record:
    return await db.fetchrow(
        """
        INSERT INTO users (email, password_hash, role)
        VALUES ($1, $2, $3)
        RETURNING id, email, role, is_active, created_at
        """,
        email,
        password_hash,
        role,
    )


async def get_by_email(db: Executor, email: str) -> asyncpg.Record | None:
    return await db.fetchrow(
        """
        SELECT id, email, password_hash, role, is_active, created_at
        FROM users
        WHERE email = $1
        """,
        email,
    )


async def get_by_id(db: Executor, user_id: uuid.UUID) -> asyncpg.Record | None:
    return await db.fetchrow(
        """
        SELECT id, email, role, is_active, created_at
        FROM users
        WHERE id = $1
        """,
        user_id,
    )
