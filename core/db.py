"""SQLite helpers — WAL, busy_timeout, and optional shared bot connection."""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, TypeVar

import aiosqlite  # type: ignore

from core.config import DB_PATH

if TYPE_CHECKING:
    from bot.app import ClanBot

DEFAULT_BUSY_TIMEOUT_MS = 15_000

T = TypeVar("T")


async def configure_sqlite(
    db: aiosqlite.Connection,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> None:
    """Apply pragmas every connection should use (WAL is persistent on the file)."""
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")


def is_db_locked_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


@asynccontextmanager
async def open_db(path: str = DB_PATH, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS):
    """Open SQLite with WAL + busy_timeout so concurrent handlers wait instead of failing."""
    async with aiosqlite.connect(path) as db:
        await configure_sqlite(db, busy_timeout_ms=busy_timeout_ms)
        yield db


async def run_db_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    retries: int = 4,
    base_delay: float = 0.05,
) -> T:
    """Retry coroutine on transient database lock errors."""
    last: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            return await fn()
        except sqlite3.OperationalError as exc:
            if not is_db_locked_error(exc) or attempt == retries - 1:
                raise
            last = exc
            await asyncio.sleep(base_delay * (2**attempt))
    if last is not None:
        raise last
    raise RuntimeError("run_db_with_retry exhausted without result")


class BotDatabase:
    """One WAL connection per bot process, guarded by an asyncio lock."""

    def __init__(self, path: str = DB_PATH) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connection(self) -> aiosqlite.Connection:
        async with self._lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self.path)
                await configure_sqlite(self._conn)
            return self._conn

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None


def attach_bot_database(bot: "ClanBot") -> BotDatabase:
    """Attach shared DB helper to bot (idempotent)."""
    db = getattr(bot, "shared_db", None)
    if db is None:
        db = BotDatabase()
        bot.shared_db = db
    return db


async def get_bot_db(bot: "ClanBot") -> aiosqlite.Connection:
    return await attach_bot_database(bot).connection()
