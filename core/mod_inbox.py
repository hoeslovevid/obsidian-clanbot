"""Staff inbox — tickets, apps, setup gaps, idle LFG."""
from __future__ import annotations

from datetime import timedelta

import aiosqlite
import discord

from core.utils import obsidian_embed, EMBED_COLORS, format_timestamp_readable
from database import DB_PATH, get_guild_setting, now_utc


async def get_oldest_open_ticket(guild_id: int) -> tuple[str, str, int] | None:
    """Return (ticket_id, subject, channel_id) for the oldest open ticket, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT ticket_id, subject, channel_id FROM tickets
            WHERE guild_id=? AND status='open'
            ORDER BY
                CASE WHEN COALESCE(priority,'normal')='urgent' THEN 0 ELSE 1 END,
                COALESCE(escalated, 0) DESC,
                last_activity_at ASC
            LIMIT 1
            """,
            (guild_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1] or "Ticket"), int(row[2] or 0)


async def _ticket_sla_stats(guild_id: int) -> tuple[int, int]:
    """Return (sla_breach_count, sla_hours)."""
    sla_raw = await get_guild_setting(guild_id, "ticket_sla_hours")
    sla_h = int(sla_raw) if sla_raw and str(sla_raw).isdigit() else 4
    cutoff = (now_utc() - timedelta(hours=sla_h)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE guild_id=? AND status='open'
              AND (first_response_at IS NULL OR first_response_at='')
              AND created_at < ?
            """,
            (guild_id, cutoff),
        )
        breaches = int((await cur.fetchone())[0] or 0)
    return breaches, sla_h


async def build_mod_inbox_embed(guild: discord.Guild, *, client=None) -> discord.Embed:
    """Aggregate staff to-dos in one view."""
    sections: list[str] = []

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'",
            (guild.id,),
        )
        open_tickets = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'
            AND (first_response_at IS NULL OR first_response_at='')
            """,
            (guild.id,),
        )
        awaiting = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            "SELECT COUNT(*) FROM applications WHERE guild_id=? AND status='PENDING'",
            (guild.id,),
        )
        pending_apps = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_posts WHERE guild_id=? AND status='OPEN'",
            (guild.id,),
        )
        open_lfg = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            """
            SELECT id, mission_type, created_at FROM lfg_posts
            WHERE guild_id=? AND status='OPEN'
            ORDER BY created_at ASC LIMIT 3
            """,
            (guild.id,),
        )
        stale_lfg = await cur.fetchall()
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM suggestions WHERE guild_id=? AND status IN ('PENDING','UNDER_REVIEW')
            """,
            (guild.id,),
        )
        open_suggestions = int((await cur.fetchone())[0] or 0)

    sla_breaches, sla_h = await _ticket_sla_stats(guild.id)
    ticket_line = f"🎫 **Tickets:** {open_tickets} open ({awaiting} awaiting first reply)"
    if sla_breaches:
        ticket_line += f" · **{sla_breaches}** past **{sla_h}h** SLA"
    sections.append(ticket_line)

    oldest = await get_oldest_open_ticket(guild.id)
    if oldest:
        tid, subject, ch_id = oldest
        jump = f"https://discord.com/channels/{guild.id}/{ch_id}"
        sections.append(
            f"  ↳ Oldest: **{tid}** — {subject[:50]}{'…' if len(subject) > 50 else ''} · [jump]({jump})"
        )

    sections.append(f"📝 **Applications:** {pending_apps} pending")
    sections.append(f"💡 **Suggestions:** {open_suggestions} need review")
    sections.append(f"🤝 **LFG:** {open_lfg} open posts")
    if stale_lfg:
        for _id, mission, created in stale_lfg:
            sections.append(f"  - #{_id} {mission} (since {format_timestamp_readable(created)[:16]})")

    try:
        from commands.general.setup_status import setup_health_line

        sections.append(f"\n🧭 {await setup_health_line(guild)}")
    except Exception:
        pass

    sections.append("\n-# `/mod dashboard` · `/admin setup_status` · `/community suggest`")

    return obsidian_embed(
        "📥 Mod Inbox",
        "\n".join(sections),
        color=EMBED_COLORS.get("moderation", discord.Color.orange()),
        footer="Use **Update data** · **Oldest ticket** / **Setup status** buttons below",
        client=client,
    )
