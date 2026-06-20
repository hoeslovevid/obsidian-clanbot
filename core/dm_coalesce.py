"""Coalesce multiple bot DMs to the same user within a short window."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import discord

from core.safe_send import safe_dm

logger = logging.getLogger(__name__)

COALESCE_SECONDS = 300.0  # 5 minutes


@dataclass
class _PendingDm:
    sections: list[tuple[str, discord.Embed]] = field(default_factory=list)
    views: list[discord.ui.View] = field(default_factory=list)
    first_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_buffers: dict[tuple[int, int], _PendingDm] = {}
_lock = asyncio.Lock()


async def queue_coalesced_dm(
    bot: discord.Client,
    guild_id: int,
    user_id: int,
    section: str,
    embed: discord.Embed,
    *,
    view: Optional[discord.ui.View] = None,
    force_immediate: bool = False,
) -> None:
    """Buffer a DM section; flush after COALESCE_SECONDS unless force_immediate."""
    user = bot.get_user(user_id)
    if not user:
        try:
            user = await bot.fetch_user(user_id)
        except Exception:
            return
    if force_immediate:
        await safe_dm(user, embed=embed, view=view)
        return

    key = (guild_id, user_id)
    async with _lock:
        pending = _buffers.get(key)
        if pending is None:
            pending = _PendingDm()
            _buffers[key] = pending
        pending.sections.append((section, embed))
        if view is not None:
            pending.views.append(view)

        age = (datetime.now(timezone.utc) - pending.first_at).total_seconds()
        if age >= COALESCE_SECONDS:
            await _flush_key(bot, key)


async def _flush_key(bot: discord.Client, key: tuple[int, int]) -> None:
    pending = _buffers.pop(key, None)
    if not pending or not pending.sections:
        return
    guild_id, user_id = key
    user = bot.get_user(user_id)
    if not user:
        try:
            user = await bot.fetch_user(user_id)
        except Exception:
            return

    if len(pending.sections) == 1:
        _sec, emb = pending.sections[0]
        view = pending.views[0] if pending.views else None
        await safe_dm(user, embed=emb, view=view)
        return

    combined = discord.Embed(
        title="📬 Obsidian updates",
        description=f"Batched **{len(pending.sections)}** alerts from your server:",
        color=discord.Color.blue(),
    )
    for section, emb in pending.sections[:8]:
        body = emb.description or emb.title or "—"
        if len(body) > 400:
            body = body[:397] + "…"
        combined.add_field(name=section, value=body, inline=False)
    if len(pending.sections) > 8:
        combined.set_footer(text=f"+ {len(pending.sections) - 8} more alerts")
    await safe_dm(user, embed=combined)


async def flush_all_coalesced_dms(bot: discord.Client) -> None:
    """Flush every buffered DM (called from background loop)."""
    async with _lock:
        keys = list(_buffers.keys())
    for key in keys:
        async with _lock:
            pending = _buffers.get(key)
            if not pending:
                continue
            age = (datetime.now(timezone.utc) - pending.first_at).total_seconds()
            if age >= COALESCE_SECONDS:
                await _flush_key(bot, key)
