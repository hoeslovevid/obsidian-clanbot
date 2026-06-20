"""Post a release note to configured guild channels when BOT_VERSION changes."""
from __future__ import annotations

import logging
from typing import Optional

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.changelog import (
    CURRENT_RELEASE_DATE,
    format_release_summary,
    get_release_announce_changes,
)
from core.config import BOT_VERSION
from core.embed_links import LinkRowView, help_link_buttons
from core.embed_templates import embed_template
from database import DB_PATH, get_guild_setting, now_utc, set_guild_setting

logger = logging.getLogger(__name__)

_SETTING_PREFIX = "release_announced_version:"


def build_release_announce_embed(
    bot: discord.Client,
    *,
    version: Optional[str] = None,
) -> discord.Embed:
    """Showcase embed for the current release only (never CHANGELOG_HISTORY)."""
    ver = version or BOT_VERSION
    bullets = get_release_announce_changes()
    summary = format_release_summary(bullets)
    return embed_template(
        "showcase",
        f"🚀 Obsidian Bot v{ver}",
        summary,
        category="general",
        footer=f"Released {CURRENT_RELEASE_DATE} · /whatsnew",
        client=bot,
    )


async def _resolve_changelog_channel_id(guild_id: int) -> Optional[int]:
    """Guild changelog channel: setting first, then update_log_settings, then log_channels."""
    raw = await get_guild_setting(guild_id, "changelog_channel_id")
    if raw and str(raw).isdigit():
        return int(raw)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id FROM update_log_settings WHERE guild_id=? AND channel_id IS NOT NULL",
                (guild_id,),
            )
            row = await cur.fetchone()
            if row and row[0]:
                return int(row[0])
    except Exception:
        pass
    try:
        from database import get_log_channel_id

        return await get_log_channel_id(guild_id, "changelog")
    except Exception:
        return None


async def _already_announced(guild_id: int, version: str) -> bool:
    """True if this guild already received a release post for ``version``."""
    marker = await get_guild_setting(guild_id, f"{_SETTING_PREFIX}{version}")
    if marker == "1":
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT 1 FROM update_log_posted_versions WHERE guild_id=? AND version=?",
                (guild_id, version),
            )
            return await cur.fetchone() is not None
    except Exception:
        return False


async def _mark_announced(guild_id: int, version: str) -> None:
    await set_guild_setting(guild_id, f"{_SETTING_PREFIX}{version}", "1")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO update_log_posted_versions (guild_id, version, posted_at)
                VALUES (?, ?, ?)
                """,
                (guild_id, version, now_utc().isoformat()),
            )
            await db.commit()
    except Exception as exc:
        logger.debug("[release] update_log_posted_versions mark failed: %s", exc)


async def _dm_changelog_subscribers(
    bot: discord.Client,
    guild: discord.Guild,
    embed: discord.Embed,
    *,
    view: Optional[discord.ui.View] = None,
) -> None:
    try:
        from commands.general.whatsnew import get_changelog_subscribers

        subscribers = await get_changelog_subscribers(guild.id)
        if not subscribers:
            return
        sent = 0
        for uid in subscribers:
            try:
                member = guild.get_member(uid)
                if not member or member.bot:
                    continue
                if view is not None:
                    await member.send(embed=embed, view=view)
                else:
                    await member.send(embed=embed)
                sent += 1
            except (discord.Forbidden, discord.HTTPException):
                continue
        logger.info(
            "[release] DMed changelog v%s to %s/%s subscribers in %s",
            BOT_VERSION,
            sent,
            len(subscribers),
            guild.name,
        )
    except Exception as exc:
        logger.debug("[release] changelog DM step failed: %s", exc)


async def post_release_to_channel(
    bot: discord.Client,
    guild: discord.Guild,
    channel: discord.TextChannel,
    *,
    version: Optional[str] = None,
    mark_posted: bool = True,
) -> bool:
    """Post the current-release embed to a channel. Returns True on success."""
    ver = version or BOT_VERSION
    embed = build_release_announce_embed(bot, version=ver)
    view = LinkRowView(*help_link_buttons())
    await channel.send(embed=embed, view=view)
    if mark_posted:
        await _mark_announced(guild.id, ver)
        await _dm_changelog_subscribers(bot, guild, embed, view=view)
    return True


async def announce_release_if_needed(bot: discord.Client) -> None:
    """For each guild, post once per BOT_VERSION when a changelog channel is configured."""
    if not BOT_VERSION:
        return
    if not get_release_announce_changes():
        logger.info("[release] No CURRENT_RELEASE_CHANGES for v%s — skipping channel announce", BOT_VERSION)
        return

    for guild in bot.guilds:
        try:
            if await _already_announced(guild.id, BOT_VERSION):
                continue
            channel_id = await _resolve_changelog_channel_id(guild.id)
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            me = guild.me
            if not me:
                continue
            perms = channel.permissions_for(me)
            if not perms.send_messages or not perms.embed_links:
                continue

            await post_release_to_channel(bot, guild, channel)
            logger.info("[release] Announced v%s in %s (#%s)", BOT_VERSION, guild.name, channel.name)
        except Exception as exc:
            logger.debug("[release] skip guild %s: %s", guild.id, exc)
