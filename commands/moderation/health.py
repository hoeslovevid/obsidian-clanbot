"""Bot health diagnostics for moderators (/admin health)."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

import aiosqlite
import discord

from core.config import BOT_VERSION, COMMAND_SYNC_GUILD_ONLY, GUILD_ID
from core.command_sync import should_use_guild_sync, sync_scope_description
from core.command_tree_stats import collect_command_tree_stats, format_command_tree_field
from core.error_handling import RECENT_ERRORS
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
    sync_guild_id = getattr(bot, "_command_sync_guild_id", None)
    if sync_guild_id is None and should_use_guild_sync():
        sync_guild_id = GUILD_ID or None

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

    version = BOT_VERSION or "unknown"

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
        name="Guilds (bot)",
        value=str(len(bot.guilds)),
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

    if cmd_stats.headroom_warnings:
        embed.add_field(
            name="📊 Command headroom (≥23/25)",
            value="\n".join(cmd_stats.headroom_warnings[:8]),
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

    try:
        from database import _SETTINGS_CACHE

        settings_cached = len(_SETTINGS_CACHE)
    except Exception:
        settings_cached = 0

    try:
        from core.cache_utils import cache_stats as wf_cache_stats

        wf_cached = wf_cache_stats()
    except Exception:
        wf_cached = "n/a"

    try:
        from bot.app import _vc_panel_update_pending

        vc_pending = sum(1 for t in _vc_panel_update_pending.values() if not t.done())
    except Exception:
        vc_pending = 0

    digest_subs = 0
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM guild_settings WHERE key LIKE 'user_digest_dm:%' AND value='1'"
            )
            digest_subs = int((await cur.fetchone())[0] or 0)
    except Exception:
        pass

    embed.add_field(
        name="Caches",
        value=f"Guild settings: **{settings_cached}** entries\nWarframe: {wf_cached}",
        inline=True,
    )
    embed.add_field(
        name="VC / digest",
        value=f"Pending VC panel updates: **{vc_pending}**\nDigest subscribers: **{digest_subs}**",
        inline=True,
    )

    try:
        from core.command_usage_report import (
            format_usage_field,
            guild_top_commands,
            never_used_commands,
        )

        top = await guild_top_commands(guild.id, limit=8)
        unused = await never_used_commands(bot, guild.id, limit=6)
        embed.add_field(
            name="Command usage",
            value=format_usage_field(top, unused=unused),
            inline=False,
        )
    except Exception:
        pass

    if GUILD_ID and guild.id != GUILD_ID and COMMAND_SYNC_GUILD_ONLY:
        embed.set_footer(text=f"Note: COMMAND_SYNC_GUILD_ONLY targets guild {GUILD_ID}")
    elif not should_use_guild_sync():
        embed.set_footer(text=f"Command sync: {sync_scope_description(sync_guild_id)} · {len(bot.guilds)} guilds")

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

    errors_decorator = (
        group.command(name="errors", description="Recent slash-command errors (session digest).")
        if group
        else bot.tree.command(name="errors", description="Recent slash-command errors.")
    )

    @errors_decorator
    async def errors(interaction: discord.Interaction):
        if (
            not interaction.guild
            or not isinstance(interaction.user, discord.Member)
            or not is_mod(interaction.user)
        ):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can view error analytics.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        lines_session = []
        if RECENT_ERRORS:
            from collections import Counter

            by_code: Counter[str] = Counter()
            by_cmd: Counter[str] = Counter()
            for entry in list(RECENT_ERRORS)[-15:]:
                code = str(entry.get("code", "?"))
                cmd = str(entry.get("command") or "?")
                by_code[code] += 1
                by_cmd[cmd] += 1
                at = str(entry.get("at", ""))[:19]
                exc_type = entry.get("exc_type", "?")
                lines_session.append(f"• `{code}` · `/{cmd}` · {exc_type} · {at}")
            top_codes = ", ".join(f"`{c}`×{n}" for c, n in by_code.most_common(5))
            top_cmds = ", ".join(f"`/{c}`×{n}" for c, n in by_cmd.most_common(5))
            session_block = (
                f"**Session ({len(RECENT_ERRORS)} in memory)**\n"
                f"Top codes: {top_codes or '—'}\n"
                f"Top commands: {top_cmds or '—'}\n"
                + ("\n".join(lines_session[-8:]) if lines_session else "")
            )
        else:
            session_block = "_No errors recorded this session._"

        db_lines: list[str] = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_error_log'"
                )
                if await cur.fetchone():
                    cur = await db.execute(
                        "SELECT at, code, command, exc_type FROM bot_error_log "
                        "ORDER BY id DESC LIMIT 10"
                    )
                    for at, code, cmd, exc_type in await cur.fetchall():
                        db_lines.append(
                            f"• `{code}` · `/{cmd or '?'}` · {exc_type} · {str(at)[:19]}"
                        )
        except Exception:
            pass

        embed = obsidian_embed(
            "📋 Error digest",
            session_block,
            color=discord.Color.orange(),
            fields=[("Persisted (last 10)", "\n".join(db_lines) or "—", False)] if db_lines else None,
            footer="Session log clears on restart · DB keeps last 200",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    export_decorator = (
        group.command(name="errors_export", description="Export persisted errors (last 24h) as a text file.")
        if group
        else bot.tree.command(name="errors_export", description="Export persisted errors (last 24h).")
    )

    @export_decorator
    async def errors_export(interaction: discord.Interaction):
        if (
            not interaction.guild
            or not isinstance(interaction.user, discord.Member)
            or not is_mod(interaction.user)
        ):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can export error logs.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        lines: list[str] = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_error_log'"
                )
                if await cur.fetchone():
                    cur = await db.execute(
                        """
                        SELECT at, code, command, exc_type, exc_msg
                        FROM bot_error_log
                        WHERE datetime(at) >= datetime('now', '-1 day')
                        ORDER BY id DESC
                        LIMIT 200
                        """
                    )
                    for at, code, cmd, exc_type, exc_msg in await cur.fetchall():
                        lines.append(
                            f"{str(at)[:19]} | {code} | /{cmd or '?'} | {exc_type} | {(exc_msg or '')[:120]}"
                        )
        except Exception as exc:
            lines.append(f"Export failed: {exc}")
        if not lines:
            lines.append("No persisted errors in the last 24 hours.")
        body = "\n".join(lines)
        if len(body) > 1900:
            import io
            fp = io.BytesIO(body.encode("utf-8"))
            fp.seek(0)
            await interaction.followup.send(
                "Error log export (last 24h):",
                file=discord.File(fp, filename="bot_errors_24h.txt"),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Error export (24h)",
                    f"```\n{body[:1800]}\n```",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
