"""Audit logging for key moderator and user actions."""
import logging
from typing import Optional, Any

import aiosqlite  # type: ignore
import discord  # type: ignore

from database import DB_PATH, now_utc, get_log_channel_id
from core.utils import obsidian_embed

logger = logging.getLogger(__name__)


async def ensure_audit_table():
    """Ensure audit_log table exists."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor_id INTEGER NOT NULL,
                target_id INTEGER,
                target_type TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_guild ON audit_log(guild_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)")
        await db.commit()


async def log_audit(
    guild_id: int,
    action: str,
    actor_id: int,
    *,
    target_id: Optional[int] = None,
    target_type: Optional[str] = None,
    details: Optional[str] = None,
    bot: Optional[Any] = None,
) -> None:
    """Log an audit event to DB and optionally post to audit channel."""
    await ensure_audit_table()
    created = now_utc().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO audit_log (guild_id, action, actor_id, target_id, target_type, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, action, actor_id, target_id, target_type, (details or "")[:500], created),
        )
        await db.commit()

    ch_id = await get_log_channel_id(guild_id, "audit")
    if ch_id and bot:
        guild = bot.get_guild(guild_id)
        if guild:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    actor = guild.get_member(actor_id)
                    actor_mention = actor.mention if actor else f"<@{actor_id}>"
                    target_mention = f"<@{target_id}>" if target_id and target_type == "user" else (str(target_id) if target_id else "—")
                    emb = obsidian_embed(
                        f"📋 Audit: {action}",
                        f"**Actor:** {actor_mention}\n**Target:** {target_mention}\n**Details:** {details or '—'}",
                        color=discord.Color.dark_grey(),
                        client=bot,
                    )
                    emb.set_footer(text=f"Guild: {guild.id} • {created[:19]}")
                    await ch.send(embed=emb)
                except Exception as e:
                    logger.warning(f"Failed to post audit to channel: {e}")
