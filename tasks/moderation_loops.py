"""Moderation background sweeps (inactive roles, server goals)."""
from __future__ import annotations

import logging
from datetime import timedelta, timezone

import discord  # type: ignore

from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import now_utc

logger = logging.getLogger(__name__)


async def run_inactive_role_sweep_cycle(bot: discord.Client) -> None:
    from commands.moderation.inactive_role import (
        get_inactive_role_id, get_inactive_threshold_days, _last_activity_for,
        was_inactive_warned, mark_inactive_warned,
    )
    from core.utils import obsidian_embed
    for guild in bot.guilds:
        try:
            role_id = await get_inactive_role_id(guild.id)
            if not role_id:
                continue
            role = guild.get_role(role_id)
            if role is None:
                continue
            me = guild.me
            if me is None or role >= me.top_role:
                # Discord won't let us assign a role at/above our top role
                continue
            threshold = await get_inactive_threshold_days(guild.id)
            cutoff = now_utc() - timedelta(days=threshold)
            warn_days = max(1, int(threshold * 0.75))
            warn_cutoff = now_utc() - timedelta(days=warn_days)
            tagged = 0
            warned = 0
            for member in guild.members:
                if member.bot or role in member.roles:
                    continue
                last = await _last_activity_for(guild.id, member.id)
                if last is None:
                    joined = member.joined_at
                    if joined is None:
                        continue
                    ref_dt = joined if joined.tzinfo else joined.replace(tzinfo=timezone.utc)
                else:
                    ref_dt = last
                if ref_dt < cutoff:
                    try:
                        await member.add_roles(role, reason=f"Inactive {threshold}d (auto-sweep)")
                        tagged += 1
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logger.debug(f"[inactive_role] could not tag {member.id}: {e}")
                elif ref_dt < warn_cutoff and not await was_inactive_warned(guild.id, member.id):
                    days_left = max(1, threshold - warn_days)
                    try:
                        dm = obsidian_embed(
                            "⚠️ Inactivity Notice",
                            f"You haven't been active in **{guild.name}** for about **{warn_days}** days.\n\n"
                            f"In **~{days_left}** more days you may receive the {role.mention} role "
                            f"(threshold: **{threshold}** days).\n\n"
                            f"_Chat, use commands, or join voice to stay active._",
                            color=discord.Color.orange(),
                            client=bot,
                        )
                        await safe_dm(member,embed=dm)
                        await mark_inactive_warned(guild.id, member.id)
                        warned += 1
                    except (discord.Forbidden, discord.HTTPException):
                        await mark_inactive_warned(guild.id, member.id)
            if tagged:
                logger.info(f"[inactive_role] tagged {tagged} member(s) in {guild.name}")
            if warned:
                logger.info(f"[inactive_role] warned {warned} member(s) in {guild.name}")
        except Exception as e:
            logger.warning(f"[inactive_role] guild {guild.id} sweep failed: {e}")


async def run_goal_progress_cycle(bot: discord.Client) -> None:
    """Recompute server-wide goal progress every 15 minutes."""
    from commands.general.server_goals import evaluate_active_goal
    for guild in bot.guilds:
        try:
            await evaluate_active_goal(guild, bot)
        except Exception as e:
            logger.debug(f"[server_goals] guild {guild.id} eval failed: {e}")

