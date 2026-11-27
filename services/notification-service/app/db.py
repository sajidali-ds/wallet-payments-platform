import asyncpg
from asyncpg.pool import PoolConnectionProxy

# Repositories accept either a Pool (one auto-committed query) or a Connection
# (so a service can run several repository calls inside ONE transaction later).
Executor = asyncpg.Pool | asyncpg.Connection | PoolConnectionProxy


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
