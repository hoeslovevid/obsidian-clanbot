"""
Channel resolution and management functions.
This module handles channel finding, creation, and resolution logic.
"""
import logging
import discord  # type: ignore
from typing import Optional
import aiosqlite  # type: ignore

from database import get_guild_setting, set_guild_setting, DB_PATH
from utils import MOD_ROLE_NAME, get_mod_role

logger = logging.getLogger(__name__)


async def find_or_create_text_channel(guild: discord.Guild, *, name: str) -> discord.TextChannel:
    """Find or create a text channel by name."""
    existing = discord.utils.get(guild.text_channels, name=name)
    if existing:
        return existing
    return await guild.create_text_channel(name=name, reason="Obsidian bot auto-setup")


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
    
    saved = await get_guild_setting(guild.id, setting_key)
    if saved and saved.isdigit():
        ch = guild.get_channel(int(saved))
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            return ch.id

    if env_id:
        ch = guild.get_channel(env_id)
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            await set_guild_setting(guild.id, setting_key, str(ch.id))
            return ch.id

    # find by exact name match (case-sensitive)
    ch = discord.utils.get(guild.channels, name=fallback_name)
    if ch:
        await set_guild_setting(guild.id, setting_key, str(ch.id))
        return ch.id

    # find by case-insensitive name match (in case moderators created it with different casing)
    fallback_lower = fallback_name.lower()
    for ch in guild.channels:
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            if ch.name.lower() == fallback_lower:
                logger.info(f"Found existing channel '{ch.name}' for {setting_key} (case-insensitive match)")
                await set_guild_setting(guild.id, setting_key, str(ch.id))
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
                    return ch.id

    if not AUTO_SETUP:
        return 0

    # Create channel if AUTO_SETUP enabled
    created = await find_or_create_text_channel(guild, name=fallback_name)
    await set_guild_setting(guild.id, setting_key, str(created.id))
    return created.id


async def resolve_temp_vc_category(guild: discord.Guild) -> discord.CategoryChannel:
    """Resolve the Temp VCs category channel."""
    from bot import TEMP_VC_CATEGORY_ID, TEMP_VC_CATEGORY_NAME, AUTO_SETUP
    
    if TEMP_VC_CATEGORY_ID:
        cat = guild.get_channel(TEMP_VC_CATEGORY_ID)
        if isinstance(cat, discord.CategoryChannel):
            return cat

    cat = discord.utils.get(guild.categories, name=TEMP_VC_CATEGORY_NAME)
    if isinstance(cat, discord.CategoryChannel):
        return cat

    if not AUTO_SETUP:
        raise RuntimeError("Temp VC category not found. Set TEMP_VC_CATEGORY_ID or TEMP_VC_CATEGORY_NAME.")
    return await guild.create_category(name=TEMP_VC_CATEGORY_NAME, reason="Obsidian bot auto-setup")


async def ensure_join_to_create_channel(guild: discord.Guild) -> int:
    """
    Ensures the join-to-create trigger voice channel exists inside the Temp VCs category.
    Saves it into guild_settings: create_vc_channel_id
    """
    from bot import CREATE_VC_NAME
    
    saved = await get_guild_setting(guild.id, "create_vc_channel_id")
    if saved and saved.isdigit():
        ch = guild.get_channel(int(saved))
        if isinstance(ch, discord.VoiceChannel):
            return ch.id

    category = await resolve_temp_vc_category(guild)

    existing = discord.utils.get(category.voice_channels, name=CREATE_VC_NAME)
    if isinstance(existing, discord.VoiceChannel):
        await set_guild_setting(guild.id, "create_vc_channel_id", str(existing.id))
        return existing.id

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
    }
    vc = await guild.create_voice_channel(
        name=CREATE_VC_NAME,
        category=category,
        overwrites=overwrites,
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


async def delete_temp_vc_and_panel(guild: discord.Guild, vc_id: int, *, reason: str):
    """Delete a temporary VC and its associated panel message."""
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
