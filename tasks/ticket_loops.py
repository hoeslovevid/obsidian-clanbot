"""Ticket SLA background checks (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.utils import get_mod_role, obsidian_embed
from database import DB_PATH, get_guild_setting, get_log_channel_id, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def run_ticket_sla_breach_cycle(bot: discord.Client) -> None:
    """Ping mod channel when open tickets lack first response past SLA."""
    from core.utils import get_mod_role
    from database import get_log_channel_id

    for guild in bot.guilds:
        try:
            sla_raw = await get_guild_setting(guild.id, "ticket_sla_hours")
            sla_h = int(sla_raw) if sla_raw and str(sla_raw).isdigit() else 4
            cutoff = (now_utc() - timedelta(hours=sla_h)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT ticket_id, subject, channel_id FROM tickets
                    WHERE guild_id=? AND status='open'
                      AND (first_response_at IS NULL OR first_response_at='')
                      AND created_at < ?
                    LIMIT 5
                    """,
                    (guild.id, cutoff),
                )
                rows = await cur.fetchall()
            if not rows:
                continue
            ch_id = await get_log_channel_id(guild.id, "tickets") or await get_guild_setting(guild.id, "ticket_log_channel_id")
            ch = guild.get_channel(int(ch_id)) if ch_id and str(ch_id).isdigit() else None
            if not isinstance(ch, discord.TextChannel):
                continue
            mod_role = await get_mod_role(guild)
            mention = mod_role.mention if mod_role else ""
            for ticket_id, subject, tch in rows:
                warn_key = f"ticket_sla_warn:{ticket_id}"
                if await get_guild_setting(guild.id, warn_key):
                    continue
                from core.safe_send import safe_channel_send

                await safe_channel_send(
                    ch,
                    content=mention,
                    embed=obsidian_embed(
                        "ΓÅ▒∩╕Å Ticket SLA breach",
                        f"**{ticket_id}** ΓÇö {subject[:80]}\nNo first response in **{sla_h}h**.",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                )
                await set_guild_setting(guild.id, warn_key, "1")
        except Exception:
            continue

