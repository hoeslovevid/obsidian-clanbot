"""
Shared utilities and helper functions for the Obsidian Clan Bot.
"""
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import discord  # type: ignore
import dateparser  # type: ignore

logger = logging.getLogger(__name__)

# Guild setting key for level-up announcement channel
XP_LEVELUP_CHANNEL_KEY = "xp_levelup_channel_id"

# Default celebration image for level-up embeds (party popper / sparkles)
LEVELUP_IMAGE_URL = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f389.png"

# Economy config from config.py (single source of truth)
from config import (
    MOD_ROLE_NAME, TIMEZONE, ECONOMY_ENABLED,
    COINS_PER_MESSAGE, COINS_PER_MINUTE_VOICE, COINS_DAILY_REWARD,
    MESSAGE_COOLDOWN_SECONDS, MIN_VOICE_MINUTES_FOR_REWARD,
)

# XP System
XP_ENABLED = os.getenv("XP_ENABLED", "true").lower() == "true"
XP_PER_MESSAGE = int(os.getenv("XP_PER_MESSAGE", "20"))  # Doubled from 10
XP_PER_MINUTE_VOICE = int(os.getenv("XP_PER_MINUTE_VOICE", "10"))  # Doubled from 5
XP_LEVEL_MULTIPLIER = int(os.getenv("XP_LEVEL_MULTIPLIER", "100"))
XP_LEVEL_EXPONENT = float(os.getenv("XP_LEVEL_EXPONENT", "2.25"))  # XP needed = level^exponent * multiplier (steeper = more XP at high levels)


# Discord embed limits
EMBED_DESC_MAX = 4096
EMBED_FIELD_VALUE_MAX = 1024
EMBED_FIELD_NAME_MAX = 256
EMBED_TITLE_MAX = 256
AUTOCOMPLETE_MAX_CHOICES = 25


def truncate_field(value: str, max_len: int = EMBED_FIELD_VALUE_MAX) -> str:
    """Truncate field value to Discord limit, with ellipsis."""
    if not value or len(value) <= max_len:
        return value or ""
    return value[: max_len - 3] + "..."


def truncate_desc(desc: str, max_len: int = EMBED_DESC_MAX) -> str:
    """Truncate embed description to Discord limit."""
    if not desc or len(desc) <= max_len:
        return desc or ""
    return desc[: max_len - 3] + "..."


def error_embed(title: str, message: str, *, client=None) -> discord.Embed:
    """Consistent error embed format across all commands."""
    return obsidian_embed(
        f"❌ {title}" if not title.startswith("❌") else title,
        truncate_desc(str(message)),
        color=discord.Color.red(),
        client=client,
    )


def message_jump_url(guild_id: int, channel_id: int, message_id: int) -> str:
    """Build Discord jump URL for a message."""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def channel_jump_url(guild_id: int, channel_id: int) -> str:
    """Build Discord channel URL for jump links."""
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


def discord_timestamp(dt: datetime, style: str = "R") -> str:
    """Format datetime as Discord timestamp. Styles: t, T, d, D, f, F, R."""
    return f"<t:{int(dt.timestamp())}:{style}>"


def format_timestamp_readable(dt, *, include_relative: bool = True) -> str:
    """
    Format datetime for readable display: full date + optional relative (e.g. "in 2 hours").
    Returns Discord timestamp format so it displays in user's locale.
    Accepts datetime or ISO string.
    """
    if dt is None:
        return "—"
    try:
        if hasattr(dt, "timestamp"):
            ts = int(dt.timestamp())
        else:
            parsed = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
            ts = int(parsed.timestamp())
        if include_relative:
            return f"<t:{ts}:f> (<t:{ts}:R>)"
        return f"<t:{ts}:f>"
    except Exception:
        return str(dt)


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def obsidian_embed(
    title: str, 
    desc: str = "", 
    *, 
    color: Optional[discord.Color] = None,
    author: Optional[discord.Member] = None,
    author_name: Optional[str] = None,
    author_icon: Optional[str] = None,
    thumbnail: Optional[str] = None,
    image: Optional[str] = None,
    footer: Optional[str] = None,
    footer_icon: Optional[str] = None,
    fields: Optional[list] = None,
    client: Optional[discord.Client] = None,
    timestamp: bool = True
) -> discord.Embed:
    """
    Create a standardized Obsidian-themed embed with enhanced styling.
    
    Args:
        title: Embed title
        desc: Embed description
        color: Embed color (defaults to Obsidian purple-blue)
        author: Discord member to set as author
        author_name: Custom author name
        author_icon: Custom author icon URL
        thumbnail: Thumbnail image URL
        image: Large image URL
        footer: Custom footer text
        footer_icon: Custom footer icon URL
        fields: List of (name, value, inline) tuples for fields
        timestamp: Whether to include timestamp (default: True)
    """
    # Default to a nice purple-blue color for Obsidian theme
    if color is None:
        color = discord.Color.from_rgb(75, 0, 130)  # Indigo/purple
    
    title = str(title)[:EMBED_TITLE_MAX]
    desc = truncate_desc(str(desc), EMBED_DESC_MAX)
    e = discord.Embed(title=title, description=desc, color=color)
    
    # Only add timestamp if requested (default True for consistency)
    if timestamp:
        e.timestamp = now_utc()
    
    # Set author (member takes priority)
    if author:
        e.set_author(
            name=author.display_name,
            icon_url=author.display_avatar.url if hasattr(author, 'display_avatar') else author.avatar.url if author.avatar else None
        )
    elif author_name:
        e.set_author(name=author_name, icon_url=author_icon)
    
    # Set thumbnail
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    
    # Set image
    if image:
        e.set_image(url=image)
    
    # Add fields (truncate to Discord limits)
    if fields:
        for field in fields:
            if len(field) == 2:
                name, value = field
                inline = False
            else:
                name, value, inline = field
            name = str(name)[:EMBED_FIELD_NAME_MAX]
            value = truncate_field(str(value), EMBED_FIELD_VALUE_MAX)
            e.add_field(name=name, value=value, inline=inline)
    
    # Set footer (default to bot name with icon if not specified)
    if footer:
        e.set_footer(text=footer, icon_url=footer_icon)
    else:
        # Use bot's actual name and avatar if client is provided
        if client and client.user:
            bot_name = client.user.display_name or client.user.name
            bot_avatar = client.user.display_avatar.url if hasattr(client.user, 'display_avatar') else client.user.avatar.url if client.user.avatar else None
            e.set_footer(text=bot_name, icon_url=bot_avatar)
        else:
            # Fallback to default if no client provided
            e.set_footer(text="Bot", icon_url=None)
    
    return e


def get_mod_role(guild: discord.Guild) -> Optional[discord.Role]:
    """Get a role with Administrator permission for VC overwrites. Uses MOD_ROLE_NAME if set, else first role with admin."""
    if MOD_ROLE_NAME:
        role = discord.utils.get(guild.roles, name=MOD_ROLE_NAME)
        if role:
            return role
    for role in sorted(guild.roles, key=lambda r: -r.position):
        if role.is_default():
            continue
        if role.permissions.administrator:
            return role
    return None


def is_mod(member: discord.Member) -> bool:
    """Check if a member has Administrator permission."""
    return member.guild_permissions.administrator


def parse_time_natural(text: str) -> Optional[datetime]:
    """
    Parse natural language time strings into timezone-aware datetime in UTC.
    Accepts: "tomorrow 8pm", "Jan 15 7:30pm", etc.
    """
    dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": TIMEZONE,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TO_TIMEZONE": "UTC",
            "PREFER_DATES_FROM": "future",
        },
    )
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_id(text: str) -> Optional[int]:
    """Extract a Discord ID from text."""
    m = re.search(r"(\d{15,25})", text or "")
    return int(m.group(1)) if m else None


async def send_levelup_announcement(
    guild: discord.Guild,
    member: discord.Member,
    level: int,
    xp: int,
    total_xp: int,
) -> bool:
    """
    Send a level-up announcement embed to the configured channel.
    Returns True if sent, False otherwise.
    """
    from database import get_guild_setting
    from database import xp_for_level, xp_for_next_level

    channel_id_str = await get_guild_setting(guild.id, XP_LEVELUP_CHANNEL_KEY)
    if not channel_id_str or not channel_id_str.isdigit():
        return False

    channel = guild.get_channel(int(channel_id_str))
    if not channel or not hasattr(channel, "send"):
        return False

    xp_needed_for_level = xp_for_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
    xp_for_next = xp_for_next_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
    xp_in_current_level = xp - xp_needed_for_level
    xp_needed_in_level = xp_for_next - xp_needed_for_level
    progress_pct = min(100, int(100 * xp_in_current_level / xp_needed_in_level)) if xp_needed_in_level > 0 else 100

    bar_filled = int(progress_pct / 10)
    bar_empty = 10 - bar_filled
    progress_bar = "▰" * bar_filled + "▱" * bar_empty

    fields = [
        ("⭐ Level", f"**{level}**", True),
        ("📊 XP", f"{xp:,} / {xp_for_next:,}", True),
        ("Progress", f"{progress_bar} {progress_pct}%", False),
    ]

    embed = obsidian_embed(
        "🎉 Level Up!",
        f"{member.mention} has leveled up to **Level {level}**!\n\n"
        f"*Keep chatting and staying active to climb even higher!*",
        color=discord.Color.gold(),
        author=member,
        thumbnail=member.display_avatar.url if member.display_avatar else None,
        image=LEVELUP_IMAGE_URL,
        fields=fields,
        footer=f"Total XP: {total_xp:,}",
        client=None,
    )

    try:
        await channel.send(embed=embed)
        return True
    except Exception as e:
        logger.warning(f"Failed to send level-up announcement: {e}")
        return False


def display_case_status(status: str) -> str:
    """Convert case status to display-friendly format."""
    s = (status or "").strip().upper()
    return {
        "OPEN": "Filed",
        "ACKNOWLEDGED": "Reviewed",
        "NEEDS INFO": "Evidence Requested",
        "RESOLVED": "Closed",
        "REJECTED": "Dismissed",
    }.get(s, status.title() if status else "Unknown")
