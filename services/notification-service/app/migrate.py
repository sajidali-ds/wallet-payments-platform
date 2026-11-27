"""Tiny migration runner: applies migrations/*.sql in filename order, once each.

Run with: python -m app.migrate
"""

import asyncio
from pathlib import Path

import asyncpg
import structlog

from app.config import get_settings
from app.logging_config import configure_logging

log = structlog.get_logger()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_LOCK_ID = 727_001  # arbitrary number, same for every instance of this service


def _discover_migrations() -> list[tuple[str, str]]:
    return [(p.name, p.read_text()) for p in sorted(MIGRATIONS_DIR.glob("*.sql"))]


async def run_migrations(dsn: str) -> list[str]:
    conn = await asyncpg.connect(dsn)
    try:
        # Advisory lock: if two containers start at once, the second waits here instead of
        # running the same migration twice. Released automatically when the connection closes.
        await conn.execute("SELECT pg_advisory_lock($1)", MIGRATION_LOCK_ID)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        rows = await conn.fetch("SELECT version FROM schema_migrations")
        applied = {row["version"] for row in rows}

        newly_applied: list[str] = []
        for name, sql in _discover_migrations():
            if name in applied:
                continue
            # The SQL and the bookkeeping row commit together or not at all.
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", name)
            newly_applied.append(name)
        return newly_applied
    finally:
        await conn.close()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    applied = asyncio.run(run_migrations(settings.database_url))
    log.info("migrations_complete", applied=applied)


if __name__ == "__main__":
    main()
