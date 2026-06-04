"""Bot health diagnostics for moderators (/admin health)."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

import aiosqlite
import discord

from core.config import GUILD_ID
from core.command_tree_stats import collect_command_tree_stats, format_command_tree_field
from core.error_handling import RECENT_ERRORS
from core.version_tracking import get_current_bot_version
from core.utils import obsidian_embed, is_mod
from database import DB_PATH, get_log_channel_id


async def build_health_embed(
    bot: discord.Client,
    guild: discord.Guild,
) -> discord.Embed:
    """Build a health-check embed (shared by command and future dashboards)."""
    db_ok = False
    db_ms: Optional[float] = None
    try:
        t0 = time.perf_counter()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("SELECT 1")
        db_ms = (time.perf_counter() - t0) * 1000
        db_ok = True
    except Exception as exc:
        db_ms = None
        db_err = str(exc)[:120]
    else:
        db_err = None

    latency_ms = round(bot.latency * 1000) if bot.latency >= 0 else None
    cmd_stats = getattr(bot, "_command_tree_stats", None) or collect_command_tree_stats(bot)
    sync_guild_id = getattr(bot, "_command_sync_guild_id", GUILD_ID or None)

    tasks_info: dict[str, Any] = getattr(bot, "_background_tasks", {}) or {}
    running = sum(1 for t in tasks_info.values() if getattr(t, "is_running", lambda: False)())
    task_total = len(tasks_info)

    last_sync = getattr(bot, "_last_command_sync", None)
    if isinstance(last_sync, datetime):
        sync_text = f"<t:{int(last_sync.timestamp())}:R>"
    else:
        sync_text = "Unknown (check startup logs)"

    start_time = getattr(bot, "start_time", None)
    if isinstance(start_time, datetime):
        uptime_text = f"<t:{int(start_time.timestamp())}:R>"
    else:
        uptime_text = "Unknown"

    bot_error_log = await get_log_channel_id(guild.id, "bot_error")

    version = getattr(bot, "_bot_version", None) or await get_current_bot_version()

    color = discord.Color.green() if db_ok and not cmd_stats.oversized else discord.Color.orange()
    embed = obsidian_embed(
        "🩺 Bot health",
        f"Version **{version}** · Guild **{guild.name}**",
        color=color,
        client=bot,
    )

    embed.add_field(
        name="Database",
        value=f"{'✅ OK' if db_ok else '❌ Failed'} ({db_ms:.0f} ms)" if db_ms is not None else f"❌ {db_err}",
        inline=True,
    )
    embed.add_field(
        name="Discord latency",
        value=f"{latency_ms} ms" if latency_ms is not None else "N/A",
        inline=True,
    )
    embed.add_field(name="Uptime since", value=uptime_text, inline=True)

    embed.add_field(
        name="Commands",
        value=format_command_tree_field(cmd_stats, sync_guild_id=sync_guild_id)
        + f"\nLast sync: {sync_text}",
        inline=False,
    )

    embed.add_field(
        name="Background tasks",
        value=f"{running}/{task_total} running",
        inline=True,
    )
    embed.add_field(
        name="Members",
        value=str(guild.member_count or len(guild.members)),
        inline=True,
    )
    embed.add_field(
        name="Bot error log",
        value="Configured ✅" if bot_error_log else "Not set — use `/mod logging setup` with **Bot Errors**",
        inline=True,
    )

    if cmd_stats.oversized:
        embed.add_field(
            name="⚠️ Sync risk (groups >25)",
            value="\n".join(cmd_stats.oversized[:8]),
            inline=False,
        )

    if RECENT_ERRORS:
        lines = []
        for entry in list(RECENT_ERRORS)[-5:]:
            cmd = entry.get("command") or "?"
            code = entry.get("code", "?")
            exc_type = entry.get("exc_type", "?")
            lines.append(f"• `{code}` · `/{cmd}` · {exc_type}")
        embed.add_field(name="Recent errors (session)", value="\n".join(lines), inline=False)

    if GUILD_ID and guild.id != GUILD_ID:
        embed.set_footer(text=f"Note: GUILD_ID env is {GUILD_ID} (this guild is {guild.id})")

    return embed


def setup(bot, group=None):
    command_decorator = (
        group.command(name="health", description="Bot health: DB, tasks, commands, recent errors.")
        if group
        else bot.tree.command(name="health", description="Bot health: DB, tasks, commands, recent errors.")
    )

    @command_decorator
    async def health(interaction: discord.Interaction):
        if (
            not interaction.guild
            or not isinstance(interaction.user, discord.Member)
            or not is_mod(interaction.user)
        ):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can view bot health.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        embed = await build_health_embed(interaction.client, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)
