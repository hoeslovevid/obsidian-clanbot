"""Guild join/leave handlers extracted from bot/app.py."""
from __future__ import annotations

import discord  # type: ignore

from core.channels import ensure_core_channels, ensure_join_to_create_channel


async def handle_guild_join(bot: discord.Client, guild: discord.Guild) -> None:
    """Run first-time setup when the bot joins a server."""
    try:
        await ensure_core_channels(guild)
        await ensure_join_to_create_channel(guild)
        print(f"[install] Ensured join-to-create in {guild.name} (guild #{len(bot.guilds)})")
    except Exception as e:
        print(f"[install] Setup failed in {guild.name}: {e}")
    from core.presence import refresh_bot_presence

    await refresh_bot_presence(bot)


async def handle_guild_remove(bot: discord.Client, guild: discord.Guild) -> None:
    """Log guild removal and refresh presence."""
    print(f"[install] Left {guild.name} (guilds remaining: {len(bot.guilds)})")
    from core.presence import refresh_bot_presence

    await refresh_bot_presence(bot)
