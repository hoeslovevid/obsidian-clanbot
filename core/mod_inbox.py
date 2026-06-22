"""Staff inbox — tickets, apps, setup gaps, idle LFG."""
from __future__ import annotations

import aiosqlite
import discord

from core.utils import obsidian_embed, EMBED_COLORS, format_timestamp_readable
from database import DB_PATH, now_utc


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

    sections.append(f"🎫 **Tickets:** {open_tickets} open ({awaiting} awaiting first reply)")
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
        footer="Use **Update data** · `/mod dashboard` · `/admin setup_status`",
        client=client,
    )
