"""Notify members when an LFG post has an open slot."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite
import discord

from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


async def _ensure_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lfg_waitlist (
                lfg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (lfg_id, user_id)
            )
            """
        )
        await db.commit()


async def add_waitlist(lfg_id: int, guild_id: int, user_id: int) -> bool:
    """Register user for slot-open notification. Returns False if already waiting."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM lfg_waitlist WHERE lfg_id=? AND user_id=?",
            (lfg_id, user_id),
        )
        if await cur.fetchone():
            return False
        await db.execute(
            "INSERT INTO lfg_waitlist (lfg_id, user_id, guild_id, created_at) VALUES (?,?,?,?)",
            (lfg_id, user_id, guild_id, now_utc().isoformat()),
        )
        await db.commit()
    return True


async def remove_waitlist(lfg_id: int, user_id: int) -> None:
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM lfg_waitlist WHERE lfg_id=? AND user_id=?", (lfg_id, user_id))
        await db.commit()


async def notify_waitlist(
    client: discord.Client,
    lfg_id: int,
    *,
    mission: str,
    channel_id: int | None,
    message_id: int | None,
    slots_open: int,
) -> int:
    """DM everyone waiting on this post. Returns count notified."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, guild_id FROM lfg_waitlist WHERE lfg_id=?",
            (lfg_id,),
        )
        rows = await cur.fetchall()
        await db.execute("DELETE FROM lfg_waitlist WHERE lfg_id=?", (lfg_id,))

    jump = ""
    if channel_id and message_id:
        jump = f"\n\n[Open post](https://discord.com/channels/@me/{channel_id}/{message_id})"

    notified = 0
    for user_id, guild_id in rows:
        user = client.get_user(user_id)
        if not user:
            try:
                user = await client.fetch_user(user_id)
            except Exception:
                continue
        emb = obsidian_embed(
            "🔔 LFG slot open",
            f"**{mission}** has **{slots_open}** slot(s) open — tap **Join** on the post.{jump}",
            color=discord.Color.green(),
            client=client,
        )
        if await safe_dm(user, embed=emb):
            notified += 1
    return notified
