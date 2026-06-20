"""Optional weekly recap DM for opted-in users."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite
import discord

from core.utils import format_number, obsidian_embed, pluralize
from database import DB_PATH, get_guild_setting, set_guild_setting


async def weekly_recap_enabled(guild_id: int, user_id: int) -> bool:
    val = await get_guild_setting(guild_id, f"user_weekly_recap:{user_id}")
    return val == "1"


async def build_weekly_recap_embed(
    guild: discord.Guild,
    user_id: int,
    *,
    client=None,
) -> discord.Embed | None:
    """Build a recap for the past 7 days, or None if nothing to report."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    lines: list[str] = []

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) FROM economy_transactions
            WHERE guild_id=? AND user_id=? AND created_at >= ? AND amount > 0
            """,
            (guild.id, user_id, since),
        )
        row = await cur.fetchone()
        earned = int(row[0] or 0) if row else 0

        cur = await db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) FROM economy_transactions
            WHERE guild_id=? AND user_id=? AND created_at >= ? AND transaction_type='XP'
            """,
            (guild.id, user_id, since),
        )
        row = await cur.fetchone()
        xp_gain = int(row[0] or 0) if row else 0

        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_posts WHERE guild_id=? AND creator_id=? AND created_at >= ?",
            (guild.id, user_id, since),
        )
        row = await cur.fetchone()
        lfg_posts = int(row[0] or 0) if row else 0

        cur = await db.execute(
            """
            SELECT COUNT(*) FROM achievements
            WHERE guild_id=? AND user_id=? AND unlocked_at >= ?
            """,
            (guild.id, user_id, since),
        )
        row = await cur.fetchone()
        ach = int(row[0] or 0) if row else 0

    if earned:
        lines.append(f"💰 **{format_number(earned)}** {pluralize(earned, 'coin')} earned")
    if xp_gain:
        lines.append(f"⭐ **{format_number(xp_gain)}** XP gained")
    if lfg_posts:
        lines.append(f"🤝 **{lfg_posts}** LFG {pluralize(lfg_posts, 'post')} created")
    if ach:
        lines.append(f"🏆 **{ach}** {pluralize(ach, 'achievement')} unlocked")

    if not lines:
        return None

    week_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return obsidian_embed(
        f"📊 Your week in {guild.name}",
        "\n".join(lines) + "\n\nKeep it up — `/today` for today's priorities.",
        color=discord.Color.blue(),
        footer=f"Week ending {week_label} · Turn off in /preferences weekly_recap",
        client=client,
    )


async def run_weekly_recap_cycle(bot: discord.Client) -> None:
    """Send recap DMs on Mondays (UTC) to opted-in users."""
    now = datetime.now(timezone.utc)
    if now.weekday() != 0:  # Monday
        return
    if not (9 <= now.hour < 12):
        return

    week_key = now.strftime("%Y-W%W")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT guild_id, key, value FROM guild_settings WHERE key LIKE 'user_weekly_recap:%' AND value='1'"
        )
        rows = await cur.fetchall()

    for guild_id, key, _val in rows:
        try:
            user_id = int(key.split(":")[-1])
        except ValueError:
            continue
        sent_key = f"user_weekly_recap_sent:{user_id}:{week_key}"
        if await get_guild_setting(int(guild_id), sent_key) == "1":
            continue
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        from core.quiet_hours import in_quiet_hours

        if await in_quiet_hours(int(guild_id), user_id):
            continue
        embed = await build_weekly_recap_embed(guild, user_id, client=bot)
        if not embed:
            continue
        member = guild.get_member(user_id)
        user = member or bot.get_user(user_id)
        if not user:
            continue
        from core.safe_send import safe_dm

        if await safe_dm(user, embed=embed):
            await set_guild_setting(int(guild_id), sent_key, "1")
