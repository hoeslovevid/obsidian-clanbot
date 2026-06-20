"""Third-party integration polling (Twitch live, etc.)."""
from __future__ import annotations

import logging
from typing import Any, Optional

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.twitch_api import (
    fetch_twitch_streams_batch,
    get_guild_twitch_settings,
    get_twitch_access_token,
    guild_twitch_setup_status,
)
from core.utils import obsidian_embed
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


def _build_live_embed(streamer_name: str, stream_data: dict[str, Any], bot: discord.Client) -> discord.Embed:
    title = stream_data.get("title", "No title")
    game = stream_data.get("game_name", "Unknown game")
    viewer_count = stream_data.get("viewer_count", 0)
    return obsidian_embed(
        f"🔴 {streamer_name} is now live!",
        f"**Title:** {title}\n**Game:** {game}\n**Viewers:** {viewer_count}\n\n"
        f"https://twitch.tv/{streamer_name}",
        color=discord.Color.purple(),
        client=bot,
    )


async def _process_guild_streamers(
    bot: discord.Client,
    guild: discord.Guild,
    *,
    live_streams: dict[str, dict[str, Any]],
    only_guild: bool = False,
) -> int:
    """Poll streamers for one guild. Returns count of notifications sent."""
    ready, reason = await guild_twitch_setup_status(guild.id)
    if not ready:
        if only_guild:
            logger.info("[twitch] guild %s skip: %s", guild.id, reason)
        return 0

    settings = await get_guild_twitch_settings(guild.id)
    assert settings is not None
    channel = guild.get_channel(int(settings["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        logger.warning("[twitch] guild %s notify channel missing", guild.id)
        return 0

    ping_role_id = settings.get("ping_role_id")
    ping_role = guild.get_role(int(ping_role_id)) if ping_role_id else None

    me = guild.me
    if me:
        perms = channel.permissions_for(me)
        if not perms.send_messages or not perms.embed_links:
            logger.warning("[twitch] guild %s missing send/embed perms in #%s", guild.id, channel.name)
            if only_guild:
                return -1
            return 0

    sent = 0
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT streamer_name, last_live_status FROM twitch_streamers WHERE guild_id=?",
            (guild.id,),
        )
        streamers = await cur.fetchall()

        for streamer_name, last_status in streamers:
            login = str(streamer_name).lower()
            stream_data = live_streams.get(login)
            is_live = stream_data is not None
            was_live = bool(last_status)

            if is_live and not was_live:
                embed = _build_live_embed(login, stream_data, bot)
                try:
                    message_content = ping_role.mention if ping_role else None
                    await channel.send(content=message_content, embed=embed)
                    await db.execute(
                        """
                        UPDATE twitch_streamers
                        SET last_live_status=1, last_notified_at=?
                        WHERE guild_id=? AND streamer_name=?
                        """,
                        (now_utc().isoformat(), guild.id, login),
                    )
                    await db.commit()
                    sent += 1
                    logger.info("[twitch] notified %s live in guild %s", login, guild.id)
                except Exception as exc:
                    logger.error("[twitch] send failed guild=%s streamer=%s: %s", guild.id, login, exc)
            elif is_live and was_live:
                # Keep DB in sync without re-notifying (handles missed intermediate polls).
                await db.execute(
                    "UPDATE twitch_streamers SET last_live_status=1 WHERE guild_id=? AND streamer_name=?",
                    (guild.id, login),
                )
                await db.commit()
            elif not is_live and was_live:
                await db.execute(
                    "UPDATE twitch_streamers SET last_live_status=0 WHERE guild_id=? AND streamer_name=?",
                    (guild.id, login),
                )
                await db.commit()
            elif not is_live and not was_live:
                await db.execute(
                    "UPDATE twitch_streamers SET last_live_status=0 WHERE guild_id=? AND streamer_name=?",
                    (guild.id, login),
                )
                await db.commit()

    return sent


async def run_twitch_live_cycle(bot: discord.Client, *, guild_id: Optional[int] = None) -> int:
    """Check monitored Twitch streamers; optionally limit to one guild (force check)."""
    if not bot.is_ready():
        return 0

    access_token = await get_twitch_access_token()
    if not access_token:
        logger.debug("[twitch] skip cycle — API credentials missing or token failed")
        return 0

    guilds = [g for g in bot.guilds if guild_id is None or g.id == guild_id]
    if guild_id is not None and not guilds:
        return 0

    all_logins: list[str] = []
    async with aiosqlite.connect(DB_PATH) as db:
        if guild_id is not None:
            cur = await db.execute(
                "SELECT streamer_name FROM twitch_streamers WHERE guild_id=?",
                (guild_id,),
            )
        else:
            cur = await db.execute("SELECT DISTINCT streamer_name FROM twitch_streamers")
        all_logins = [str(row[0]).lower() for row in await cur.fetchall()]

    if not all_logins:
        return 0

    live_streams = await fetch_twitch_streams_batch(all_logins, access_token)
    total_sent = 0
    for guild in guilds:
        try:
            total_sent += await _process_guild_streamers(
                bot,
                guild,
                live_streams=live_streams,
                only_guild=guild_id is not None,
            )
        except Exception as exc:
            logger.error("[twitch] guild %s cycle error: %s", guild.id, exc, exc_info=True)
    return total_sent
