"""Third-party integration polling (Twitch live, etc.)."""
from __future__ import annotations

import logging
from typing import Any, Optional

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.twitch_api import (
    ensure_twitch_streamer_schema,
    fetch_twitch_streams_batch,
    get_guild_twitch_settings,
    get_twitch_access_token,
    guild_twitch_setup_status,
    twitch_was_live,
)
from core.twitch_live_embed import TwitchLiveAlertView, build_twitch_live_embed
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


def _is_new_live_session(
    stream_data: dict[str, Any],
    *,
    was_live: bool,
    last_stream_id: Optional[str],
) -> bool:
    """True when we should post a go-live alert (new stream session, not mid-stream poll)."""
    stream_id = str(stream_data.get("id") or "")
    if not was_live:
        return True
    if stream_id and stream_id != (last_stream_id or ""):
        return True
    return False


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
    await ensure_twitch_streamer_schema()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT streamer_name, last_live_status, twitch_user_id, last_stream_id
            FROM twitch_streamers WHERE guild_id=?
            """,
            (guild.id,),
        )
        streamers = await cur.fetchall()

        for streamer_name, last_status, twitch_user_id, last_stream_id in streamers:
            login = str(streamer_name).lower()
            stream_data = live_streams.get(login)
            is_live = stream_data is not None
            was_live = twitch_was_live(last_status)
            stream_id = str(stream_data.get("id") or "") if stream_data else None

            if is_live and _is_new_live_session(
                stream_data,
                was_live=was_live,
                last_stream_id=last_stream_id,
            ):
                embed = build_twitch_live_embed(stream_data, client=bot)
                view = TwitchLiveAlertView(login)
                try:
                    message_content = ping_role.mention if ping_role else None
                    await channel.send(content=message_content, embed=embed, view=view)
                    await db.execute(
                        """
                        UPDATE twitch_streamers
                        SET last_live_status=1, last_stream_id=?, last_notified_at=?
                        WHERE guild_id=? AND streamer_name=?
                        """,
                        (stream_id, now_utc().isoformat(), guild.id, streamer_name),
                    )
                    await db.commit()
                    sent += 1
                    logger.info("[twitch] notified %s live in guild %s (stream %s)", login, guild.id, stream_id)
                except Exception as exc:
                    logger.error("[twitch] send failed guild=%s streamer=%s: %s", guild.id, login, exc)
            elif is_live:
                await db.execute(
                    """
                    UPDATE twitch_streamers
                    SET last_live_status=1, last_stream_id=COALESCE(?, last_stream_id)
                    WHERE guild_id=? AND streamer_name=?
                    """,
                    (stream_id, guild.id, streamer_name),
                )
                await db.commit()
            elif was_live:
                await db.execute(
                    """
                    UPDATE twitch_streamers
                    SET last_live_status=0, last_stream_id=NULL
                    WHERE guild_id=? AND streamer_name=?
                    """,
                    (guild.id, streamer_name),
                )
                await db.commit()
            else:
                await db.execute(
                    """
                    UPDATE twitch_streamers
                    SET last_live_status=0
                    WHERE guild_id=? AND streamer_name=? AND last_live_status != 0
                    """,
                    (guild.id, streamer_name),
                )
                await db.commit()

    return sent


async def run_twitch_live_cycle(bot: discord.Client, *, guild_id: Optional[int] = None) -> int:
    """Check monitored Twitch streamers; optionally limit to one guild (force check)."""
    if not bot.is_ready():
        return 0

    await ensure_twitch_streamer_schema()

    access_token = await get_twitch_access_token()
    if not access_token:
        logger.debug("[twitch] skip cycle — API credentials missing or token failed")
        return 0

    guilds = [g for g in bot.guilds if guild_id is None or g.id == guild_id]
    if guild_id is not None and not guilds:
        return 0

    all_logins: list[str] = []
    all_user_ids: list[str] = []
    async with aiosqlite.connect(DB_PATH) as db:
        if guild_id is not None:
            cur = await db.execute(
                "SELECT streamer_name, twitch_user_id FROM twitch_streamers WHERE guild_id=?",
                (guild_id,),
            )
        else:
            cur = await db.execute("SELECT DISTINCT streamer_name, twitch_user_id FROM twitch_streamers")
        for name, uid in await cur.fetchall():
            all_logins.append(str(name).lower())
            if uid:
                all_user_ids.append(str(uid))

    if not all_logins:
        return 0

    live_streams = await fetch_twitch_streams_batch(
        all_logins,
        access_token,
        user_ids=all_user_ids,
    )

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
