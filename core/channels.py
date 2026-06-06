"""
Channel resolution and management functions.
This module handles channel finding, creation, and resolution logic.
"""
import logging
import time
import discord  # type: ignore
from typing import Mapping, Optional, Union, cast
import aiosqlite  # type: ignore

from database import get_guild_setting, set_guild_setting, DB_PATH

logger = logging.getLogger(__name__)

# Resolved channel IDs per (guild, setting_key) — avoids repeated guild_settings reads.
_CHANNEL_RESOLVE_CACHE: dict[str, tuple[int, float]] = {}
_CHANNEL_RESOLVE_TTL = 300.0


def _channel_resolve_cache_key(guild_id: int, setting_key: str) -> str:
    return f"{guild_id}:{setting_key}"


def invalidate_channel_resolve_cache(
    guild_id: int,
    setting_key: Optional[str] = None,
) -> None:
    """Evict cached resolve_channel_id results (call when guild_settings change)."""
    if setting_key is None:
        prefix = f"{guild_id}:"
        for k in list(_CHANNEL_RESOLVE_CACHE.keys()):
            if k.startswith(prefix):
                del _CHANNEL_RESOLVE_CACHE[k]
        return
    _CHANNEL_RESOLVE_CACHE.pop(_channel_resolve_cache_key(guild_id, setting_key), None)


def _channel_resolve_cache_get(guild_id: int, setting_key: str) -> Optional[int]:
    ck = _channel_resolve_cache_key(guild_id, setting_key)
    entry = _CHANNEL_RESOLVE_CACHE.get(ck)
    if entry is None:
        return None
    ch_id, ts = entry
    if time.monotonic() - ts > _CHANNEL_RESOLVE_TTL:
        del _CHANNEL_RESOLVE_CACHE[ck]
        return None
    return ch_id


def _channel_resolve_cache_put(guild_id: int, setting_key: str, channel_id: int) -> None:
    _CHANNEL_RESOLVE_CACHE[_channel_resolve_cache_key(guild_id, setting_key)] = (
        channel_id,
        time.monotonic(),
    )


async def find_or_create_text_channel(guild: discord.Guild, *, name: str) -> discord.TextChannel:
    """Find or create a text channel by name."""
    existing = discord.utils.get(guild.text_channels, name=name)
    if existing:
        return existing
    return await guild.create_text_channel(name=name, reason="Bot auto-setup")


async def resolve_channel_id(
    guild: discord.Guild,
    setting_key: str,
    env_id: int,
    fallback_name: str,
) -> int:
    """
    Resolve a channel ID in this order:
    1) guild_settings value
    2) env ID (if provided)
    3) find by fallback_name (case-insensitive, partial match)
    4) create if AUTO_SETUP (only if no existing channel found)
    Saves the resolved ID into guild_settings.
    """
    from bot import AUTO_SETUP

    cached_id = _channel_resolve_cache_get(guild.id, setting_key)
    if cached_id is not None:
        ch = guild.get_channel(cached_id)
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            return ch.id
        invalidate_channel_resolve_cache(guild.id, setting_key)
    
    saved = await get_guild_setting(guild.id, setting_key)
    if saved is not None:
        if saved == "0" or str(saved).lower() == "skipped":
            _channel_resolve_cache_put(guild.id, setting_key, 0)
            return 0  # Moderator explicitly skipped during setup_obsidian
        if saved.isdigit() and int(saved) != 0:
            ch = guild.get_channel(int(saved))
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
                _channel_resolve_cache_put(guild.id, setting_key, ch.id)
                return ch.id

    if env_id:
        ch = guild.get_channel(env_id)
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            await set_guild_setting(guild.id, setting_key, str(ch.id))
            _channel_resolve_cache_put(guild.id, setting_key, ch.id)
            return ch.id

    # find by exact name match (case-sensitive)
    ch = discord.utils.get(guild.channels, name=fallback_name)
    if ch:
        await set_guild_setting(guild.id, setting_key, str(ch.id))
        _channel_resolve_cache_put(guild.id, setting_key, ch.id)
        return ch.id

    # find by case-insensitive name match (in case moderators created it with different casing)
    fallback_lower = fallback_name.lower()
    for ch in guild.channels:
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            if ch.name.lower() == fallback_lower:
                logger.info(f"Found existing channel '{ch.name}' for {setting_key} (case-insensitive match)")
                await set_guild_setting(guild.id, setting_key, str(ch.id))
                _channel_resolve_cache_put(guild.id, setting_key, ch.id)
                return ch.id

    # Before creating, check if there's already a channel that might be serving this purpose
    # by checking if any text channel contains key words from the fallback name
    if setting_key in ("voice_panel_channel_id", "complaints_channel_id", "complaints_log_channel_id", "events_channel_id"):
        # Extract key words from fallback_name (e.g., "obsidian-console" -> ["obsidian", "console"])
        # Normalize by replacing hyphens/underscores with spaces, then split
        normalized_fallback = fallback_name.replace("-", " ").replace("_", " ").lower()
        key_words = [word for word in normalized_fallback.split() if len(word) >= 2]  # Lowered threshold to catch "ops"
        
        for ch in guild.text_channels:
            ch_name_lower = ch.name.lower()
            # Normalize channel name the same way (replace hyphens/underscores with spaces for comparison)
            ch_normalized = ch_name_lower.replace("-", " ").replace("_", " ")
            
            # Check if channel name contains ALL key words (e.g., "ops-board" matches "ops board" or "ops-board" or "board-ops")
            # This is more strict than matching any single keyword
            if key_words and all(word in ch_normalized for word in key_words):
                # Found a potential match - save it and return
                logger.info(f"Found existing channel '{ch.name}' for {setting_key} (matched keywords: {key_words}, fallback: '{fallback_name}')")
                await set_guild_setting(guild.id, setting_key, str(ch.id))
                _channel_resolve_cache_put(guild.id, setting_key, ch.id)
                return ch.id
        
        # Additional fallback: for events channel, also check for common variations
        if setting_key == "events_channel_id":
            # Check for common event-related channel names
            event_keywords = ["event", "ops", "operation", "mission", "raid"]
            for ch in guild.text_channels:
                ch_name_lower = ch.name.lower()
                ch_normalized = ch_name_lower.replace("-", " ").replace("_", " ")
                # Check if channel name contains "ops" or "event" or similar
                if any(keyword in ch_normalized for keyword in event_keywords):
                    logger.info(f"Found potential events channel '{ch.name}' for {setting_key} (matched event keywords)")
                    await set_guild_setting(guild.id, setting_key, str(ch.id))
                    _channel_resolve_cache_put(guild.id, setting_key, ch.id)
                    return ch.id

    if not AUTO_SETUP:
        return 0

    # Create channel if AUTO_SETUP enabled
    created = await find_or_create_text_channel(guild, name=fallback_name)
    await set_guild_setting(guild.id, setting_key, str(created.id))
    _channel_resolve_cache_put(guild.id, setting_key, created.id)
    return created.id


async def resolve_temp_vc_category(guild: discord.Guild) -> discord.CategoryChannel:
    """Resolve the Temp VCs category channel."""
    from bot import TEMP_VC_CATEGORY_ID, TEMP_VC_CATEGORY_NAME, AUTO_SETUP

    # 1) guild_settings (from /setup_obsidian)
    saved = await get_guild_setting(guild.id, "temp_vc_category_id")
    if saved is not None:
        if saved == "0" or saved.lower() == "skipped":
            raise RuntimeError("Temp VC category was skipped during setup. Use /general setup_obsidian to configure.")
        if saved.isdigit() and int(saved) != 0:
            cat = guild.get_channel(int(saved))
            if isinstance(cat, discord.CategoryChannel):
                return cat

    if TEMP_VC_CATEGORY_ID:
        cat = guild.get_channel(TEMP_VC_CATEGORY_ID)
        if isinstance(cat, discord.CategoryChannel):
            return cat

    cat = discord.utils.get(guild.categories, name=TEMP_VC_CATEGORY_NAME)
    if isinstance(cat, discord.CategoryChannel):
        return cat

    if not AUTO_SETUP:
        raise RuntimeError("Temp VC category not found. Use /general setup_obsidian to configure.")
    return await guild.create_category(name=TEMP_VC_CATEGORY_NAME, reason="Bot auto-setup")


async def ensure_join_to_create_channel(guild: discord.Guild) -> int:
    """
    Ensures the join-to-create trigger voice channel exists inside the Temp VCs category.
    Saves it into guild_settings: create_vc_channel_id
    Returns 0 if Temp VC was skipped during setup.
    """
    from bot import CREATE_VC_NAME
    
    # If mod explicitly skipped Temp VC during setup_obsidian, don't create
    temp_cat_saved = await get_guild_setting(guild.id, "temp_vc_category_id")
    if temp_cat_saved is not None and (temp_cat_saved == "0" or temp_cat_saved.lower() == "skipped"):
        return 0
    
    saved = await get_guild_setting(guild.id, "create_vc_channel_id")
    if saved and saved.isdigit():
        ch = guild.get_channel(int(saved))
        if isinstance(ch, discord.VoiceChannel):
            return ch.id

    try:
        category = await resolve_temp_vc_category(guild)
    except RuntimeError:
        # Temp VC category not configured (use /setup_obsidian)
        return 0

    existing = discord.utils.get(category.voice_channels, name=CREATE_VC_NAME)
    if isinstance(existing, discord.VoiceChannel):
        await set_guild_setting(guild.id, "create_vc_channel_id", str(existing.id))
        return existing.id

    overwrites: dict[discord.Role, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
    }
    vc = await guild.create_voice_channel(
        name=CREATE_VC_NAME,
        category=category,
        overwrites=cast(
            Mapping[Union[discord.Role, discord.Member, discord.Object], discord.PermissionOverwrite],
            overwrites,
        ),
        reason="Auto-created join-to-create channel on bot install",
    )
    await set_guild_setting(guild.id, "create_vc_channel_id", str(vc.id))
    return vc.id


async def ensure_core_channels(guild: discord.Guild):
    """Create / resolve core text channels if AUTO_SETUP enabled or IDs set."""
    from bot import (
        VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME,
        COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME,
        COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME,
        EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME,
    )
    
    await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
    await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
    await resolve_channel_id(guild, "complaints_log_channel_id", COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME)
    await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)


async def delete_vc_panel_message(guild: discord.Guild, vc_id: int):
    """Delete the VC panel message for a given voice channel."""
    from bot import VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT message_id FROM vc_panels WHERE guild_id=? AND channel_id=?",
            (guild.id, vc_id),
        )
        row = await cur.fetchone()
        if row:
            msg_id = int(row[0])
            await db.execute("DELETE FROM vc_panels WHERE guild_id=? AND channel_id=?", (guild.id, vc_id))
            await db.commit()
        else:
            msg_id = 0

    if msg_id:
        ch_id = await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
        ch = guild.get_channel(ch_id) if ch_id else None
        if isinstance(ch, discord.TextChannel):
            # Type narrowing: ch is now guaranteed to be discord.TextChannel
            text_ch: discord.TextChannel = ch  # type: ignore
            try:
                msg = await text_ch.fetch_message(msg_id)
                if msg:
                    await msg.delete()
            except Exception:
                pass


async def delete_temp_vc_and_panel(
    guild: discord.Guild,
    vc_id: int,
    *,
    reason: str,
    bot: Optional[discord.Client] = None,
) -> None:
    """Delete a temporary VC and its associated panel message."""
    if bot is not None:
        try:
            from core.music_player import stop_if_in_channel

            await stop_if_in_channel(guild, vc_id, bot)
        except Exception as exc:
            logger.debug("[channels] music stop on temp VC delete failed: %s", exc)

    vc = guild.get_channel(vc_id)
    if isinstance(vc, discord.VoiceChannel):
        try:
            await vc.delete(reason=reason)
        except Exception:
            pass

    await delete_vc_panel_message(guild, vc_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM temp_vcs WHERE guild_id=? AND channel_id=?", (guild.id, vc_id))
        await db.commit()
