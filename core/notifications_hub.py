"""Unified personal notification status (/notifications)."""
from __future__ import annotations

import aiosqlite
import discord

from core.utils import obsidian_embed, EMBED_COLORS
from database import DB_PATH, get_digest_dm, get_guild_setting


async def build_notifications_status_embed(
    guild: discord.Guild,
    user: discord.abc.User,
    *,
    client=None,
) -> discord.Embed:
    """All watches + DM prefs in one panel."""
    uid = user.id
    gid = guild.id
    lines: list[str] = []

    from core.notify_explain import build_notify_explain_embed

    dm_embed = await build_notify_explain_embed(guild, user, client=client)
    if dm_embed.description:
        lines.append("**Personal DMs**")
        lines.append(dm_embed.description[:900])

    lines.append("\n**Warframe (guild channels)**")
    baro_row = None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id, enabled FROM baro_notification_settings WHERE guild_id=?",
            (gid,),
        )
        baro_row = await cur.fetchone()
        cur = await db.execute(
            "SELECT COUNT(*) FROM price_watches WHERE guild_id=? AND user_id=?",
            (gid, uid),
        )
        pw_count = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            "SELECT streamer_name FROM twitch_streamers WHERE guild_id=? ORDER BY streamer_name LIMIT 8",
            (gid,),
        )
        twitch = [r[0] for r in await cur.fetchall()]

    if baro_row and baro_row[1]:
        ch = guild.get_channel(int(baro_row[0])) if baro_row[0] else None
        lines.append(f"• Baro channel: {ch.mention if ch else 'configured'}")
    else:
        lines.append("• Baro channel: not set (`/wfnotify configure`)")

    wf_keys = [
        ("alerts_notify_channel_id", "Alerts"),
        ("cycle_notify_channel_id", "Cycles"),
        ("archon_notify_channel_id", "Archon"),
    ]
    for key, label in wf_keys:
        raw = await get_guild_setting(gid, key)
        if raw and str(raw).isdigit():
            ch = guild.get_channel(int(raw))
            lines.append(f"• {label}: {ch.mention if ch else 'set'}")

    lines.append(f"\n**Your watches**")
    lines.append(f"• Price watches: **{pw_count}** (`/price_watch`)")
    if twitch:
        lines.append(f"• Twitch (server): {', '.join(f'`{t}`' for t in twitch[:5])}")
    else:
        lines.append("• Twitch (server): none (`/community twitch_add`)")

    digest = await get_digest_dm(gid, uid)
    lines.append(f"• Daily digest DM: {'On' if digest else 'Off'} (`/preferences digest_dm`)")

    return obsidian_embed(
        "🔔 Notification Status",
        "\n".join(lines)[:3900],
        color=EMBED_COLORS["general"],
        footer="Test DMs: /wfnotify test_ping · Guild feeds: /wfnotify status",
        client=client,
    )
