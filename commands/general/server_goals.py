"""Item 72 — server-wide weekly goals.

Mods set a weekly goal (messages / voice_minutes / commands_used /
events_attended) with a reward (xp_multiplier or coins_multiplier).
A background loop computes guild-wide progress from `activity_stats`
and, when the target is hit, posts a celebratory message and grants
the multiplier for the configured duration via
`xp_multiplier_until` / `coins_multiplier_until` guild settings.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite  # type: ignore
import discord
from discord import app_commands

from core.utils import (
    EMBED_COLORS,
    error_embed,
    format_number,
    is_mod,
    obsidian_embed,
    render_bar,
    success_embed,
)
from database import DB_PATH, get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)

METRICS = ("messages", "voice_minutes", "commands_used", "events_attended")
REWARDS = ("xp_multiplier", "coins_multiplier")

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([dhm])\s*$", re.IGNORECASE)


async def _ensure_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS server_goals (
                guild_id INTEGER NOT NULL,
                goal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric TEXT NOT NULL,
                target INTEGER NOT NULL,
                reward_type TEXT NOT NULL,
                reward_value INTEGER NOT NULL,
                week_start DATE NOT NULL,
                week_end DATE NOT NULL,
                completed BOOLEAN NOT NULL DEFAULT 0,
                completed_at TEXT,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


def _parse_duration(text: str) -> Optional[timedelta]:
    """Parse '7d' / '12h' / '90m' into a timedelta (caps at 30d)."""
    m = _DURATION_RE.match(text or "")
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "d":
        td = timedelta(days=n)
    elif unit == "h":
        td = timedelta(hours=n)
    else:
        td = timedelta(minutes=n)
    if td <= timedelta(0):
        return None
    if td > timedelta(days=30):
        td = timedelta(days=30)
    return td


async def _aggregate_metric(guild_id: int, metric: str, since_iso: str) -> int:
    """Best-effort guild-wide aggregate from `activity_stats`."""
    column_map = {
        "messages": "messages_sent",
        "voice_minutes": "voice_minutes",
        "commands_used": "commands_used",
        "events_attended": "events_attended",
    }
    col = column_map[metric]
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                f"SELECT COALESCE(SUM({col}), 0) FROM activity_stats "
                f"WHERE guild_id=? AND last_activity_date >= ?",
                (guild_id, since_iso),
            )
            row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as e:
        logger.warning(f"[server_goals] aggregate failed: {e}")
        return 0


async def _active_goal(guild_id: int) -> Optional[tuple]:
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT goal_id, metric, target, reward_type, reward_value, week_start, week_end, completed "
            "FROM server_goals WHERE guild_id=? AND completed=0 "
            "ORDER BY goal_id DESC LIMIT 1",
            (guild_id,),
        )
        return await cur.fetchone()


async def evaluate_active_goal(guild: discord.Guild, bot) -> None:
    """Loop helper — recompute progress for the active goal & complete if hit."""
    row = await _active_goal(guild.id)
    if not row:
        return
    goal_id, metric, target, reward_type, reward_value, week_start, week_end, completed = row
    if completed:
        return
    try:
        now = datetime.now(timezone.utc)
        end_dt = datetime.fromisoformat(str(week_end).replace("Z", "+00:00"))
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if now > end_dt:
            # Window expired without completion — leave row in place but stop tracking.
            return
        start_iso = str(week_start)
        progress = await _aggregate_metric(guild.id, metric, start_iso)
        if progress < int(target):
            return
        # Complete + apply reward
        kind = "xp" if reward_type == "xp_multiplier" else "coins"
        until = (now + timedelta(days=7)).replace(microsecond=0)
        await set_guild_setting(
            guild.id,
            f"{kind}_multiplier_until",
            f"{until.isoformat()}:{int(reward_value)}",
        )
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE server_goals SET completed=1, completed_at=? WHERE goal_id=?",
                (now.isoformat(), goal_id),
            )
            await db.commit()

        # Post celebration in configured channel (or system channel).
        ch_id_raw = await get_guild_setting(guild.id, "server_goals_channel_id")
        channel = None
        if ch_id_raw and str(ch_id_raw).isdigit():
            channel = guild.get_channel(int(ch_id_raw))
        if channel is None:
            channel = guild.system_channel
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    embed=obsidian_embed(
                        "🎯 Server Goal Hit!",
                        f"The server smashed the **{metric.replace('_', ' ')}** goal "
                        f"of {format_number(int(target))}!\n\n"
                        f"Reward active until <t:{int(until.timestamp())}:F>: "
                        f"**{int(reward_value)}× {kind.upper()}** for everyone.",
                        color=EMBED_COLORS["success"],
                        client=bot,
                        brand=True,
                    )
                )
            except Exception as e:
                logger.debug(f"[server_goals] could not post celebration: {e}")
    except Exception as e:
        logger.warning(f"[server_goals] evaluation failed for {guild.id}: {e}")


def setup(bot, group=None):
    """Register `/<group> goal` subgroup. Defaults to top-level `/goal`."""
    goal_group = app_commands.Group(name="goal", description="🎯 Server-wide weekly goals.")

    @goal_group.command(name="set", description="(mods) Set a server-wide weekly goal with a reward.")
    @app_commands.describe(
        metric="What to track across the server.",
        target="Target value to hit before the deadline.",
        reward="Reward type when goal completes.",
        value="Multiplier value (e.g. 2 = 2× XP).",
        duration="How long the goal window is. Examples: 7d, 24h, 90m (max 30d).",
        channel="Channel for the completion announcement (optional).",
    )
    @app_commands.choices(
        metric=[app_commands.Choice(name=m, value=m) for m in METRICS],
        reward=[app_commands.Choice(name=r, value=r) for r in REWARDS],
    )
    async def set_goal(
        interaction: discord.Interaction,
        metric: app_commands.Choice[str],
        target: int,
        reward: app_commands.Choice[str],
        value: int,
        duration: str = "7d",
        channel: Optional[discord.TextChannel] = None,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        if target <= 0 or value <= 1:
            return await interaction.response.send_message(
                embed=error_embed("Invalid input", "Target must be > 0 and reward value must be > 1.", client=interaction.client),
                ephemeral=True,
            )
        td = _parse_duration(duration)
        if td is None:
            return await interaction.response.send_message(
                embed=error_embed("Invalid duration", "Use formats like `7d`, `24h`, `90m`.", client=interaction.client),
                ephemeral=True,
            )
        await _ensure_table()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        week_end = now + td
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE server_goals SET completed=1, completed_at=? "
                "WHERE guild_id=? AND completed=0",
                (now.isoformat(), interaction.guild.id),
            )
            await db.execute(
                "INSERT INTO server_goals (guild_id, metric, target, reward_type, reward_value, "
                "week_start, week_end, completed, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    interaction.guild.id, metric.value, int(target),
                    reward.value, int(value),
                    now.isoformat(), week_end.isoformat(),
                    interaction.user.id, now.isoformat(),
                ),
            )
            await db.commit()
        if channel:
            await set_guild_setting(interaction.guild.id, "server_goals_channel_id", str(channel.id))

        await interaction.response.send_message(
            embed=success_embed(
                "Goal set",
                f"Track **{metric.value.replace('_', ' ')}** to **{format_number(int(target))}** "
                f"by <t:{int(week_end.timestamp())}:F>.\n"
                f"Reward on completion: **{int(value)}× {reward.value.replace('_', ' ')}** for 7 days.",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @goal_group.command(name="status", description="See the current server goal progress.")
    async def status_cmd(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Server only", "Run this in a server.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer()
        row = await _active_goal(interaction.guild.id)
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🎯 No active goal",
                    "There's no server goal running right now. Mods can start one with `/tools goal set`.",
                    color=EMBED_COLORS["community"],
                    client=interaction.client,
                ),
            )
        goal_id, metric, target, reward_type, reward_value, week_start, week_end, _completed = row
        progress = await _aggregate_metric(interaction.guild.id, metric, str(week_start))
        pct = min(100.0, 100.0 * progress / int(target)) if int(target) > 0 else 0.0

        try:
            end_dt = datetime.fromisoformat(str(week_end).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except Exception:
            end_dt = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        seconds_left = (end_dt - now).total_seconds()
        if seconds_left > 0 and pct > 0:
            eta_seconds = seconds_left * (100.0 / pct) if pct < 100 else 0
            eta_line = (
                f"At the current rate the goal would complete in ~**{int(eta_seconds // 3600)}h**."
                if pct < 100 else "**Goal already completed — pending payout.**"
            )
        else:
            eta_line = "Need more activity to project an ETA."

        await interaction.followup.send(
            embed=obsidian_embed(
                "🎯 Server Goal",
                f"Metric: **{metric.replace('_', ' ')}**\n"
                f"Progress: **{format_number(progress)} / {format_number(int(target))}**\n"
                f"{render_bar(pct)}\n\n"
                f"Window ends <t:{int(end_dt.timestamp())}:R>.\n"
                f"Reward on completion: **{int(reward_value)}× {reward_type.replace('_', ' ')}** for 7 days.\n\n"
                f"{eta_line}",
                color=EMBED_COLORS["community"],
                client=interaction.client,
            ),
        )

    # tools_group is currently at the 25-subcommand cap (favorites + phishing
    # already overflow), so this group is always registered as a top-level
    # `/goal` group to avoid evicting them.
    bot.tree.add_command(goal_group)
