"""Shared SQLite connection on the bot instance (reduces connect churn)."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

import aiosqlite  # type: ignore

from core.config import DB_PATH

if TYPE_CHECKING:
    from bot.app import ClanBot


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
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute("PRAGMA busy_timeout=5000")
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
