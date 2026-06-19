"""Warframe Steam playtime role assignments."""
from __future__ import annotations

import logging
import os

import discord  # type: ignore

logger = logging.getLogger(__name__)


async def run_warframe_achievement_roles_cycle(bot: discord.Client) -> None:
    """Assign roles based on Warframe playtime and other in-game achievements."""
    from database import (
        get_all_linked_steam_accounts,
        get_warframe_achievement_roles,
        has_warframe_achievement_unlock,
        record_warframe_achievement_unlock,
        update_steam_playtime,
    )
    from api.warframe_api import fetch_steam_warframe_playtime

    if not os.environ.get("STEAM_API_KEY"):
        return

    for guild in bot.guilds:
        try:
            role_configs = await get_warframe_achievement_roles(guild.id)
            if not role_configs:
                continue

            linked = await get_all_linked_steam_accounts(guild.id)
            if not linked:
                continue

            for user_id, steam_id_64 in linked:
                try:
                    member = guild.get_member(user_id)
                    if not member:
                        continue

                    # Fetch fresh playtime
                    hours = await fetch_steam_warframe_playtime(steam_id_64)
                    if hours is None:
                        continue
                    await update_steam_playtime(guild.id, user_id, hours)

                    # Check each playtime role config
                    for ach_type, threshold, role_id in role_configs:
                        if ach_type != "playtime":
                            continue
                        if hours < threshold:
                            continue
                        if await has_warframe_achievement_unlock(guild.id, user_id, ach_type, threshold):
                            continue

                        role = guild.get_role(role_id)
                        if not role:
                            continue
                        if role in member.roles:
                            await record_warframe_achievement_unlock(guild.id, user_id, ach_type, threshold)
                            continue
                        if not guild.me.guild_permissions.manage_roles:
                            continue
                        if guild.me.top_role <= role:
                            continue

                        try:
                            await member.add_roles(role, reason=f"Warframe playtime: {hours:,}h (≥{threshold:,}h)")
                            await record_warframe_achievement_unlock(guild.id, user_id, ach_type, threshold)
                            logger.info(f"[warframe_roles] Assigned {role.name} to {member} ({hours}h playtime)")
                        except discord.Forbidden:
                            logger.warning(f"[warframe_roles] Cannot assign role to {member}")
                        except Exception as e:
                            logger.error(f"[warframe_roles] Error assigning role: {e}")
                except Exception as e:
                    logger.error(f"[warframe_roles] Error processing user {user_id}: {e}")
        except Exception as e:
            logger.error(f"[warframe_roles] Error processing guild {guild.id}: {e}")

