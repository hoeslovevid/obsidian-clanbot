"""
Shared utilities and helper functions for the Obsidian Clan Bot.
"""
import os
import re
from datetime import datetime, timezone
from typing import Optional

import discord
import dateparser

# Import config from bot (will be set when bot.py loads)
MOD_ROLE_NAME = os.getenv("MOD_ROLE_NAME", "Obsidian Inheritor")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
DB_PATH = os.getenv("DB_PATH", "obsidian_clanbot.db")
ECONOMY_ENABLED = os.getenv("ECONOMY_ENABLED", "true").lower() == "true"
COINS_PER_MESSAGE = int(os.getenv("COINS_PER_MESSAGE", "5"))
COINS_PER_MINUTE_VOICE = int(os.getenv("COINS_PER_MINUTE_VOICE", "2"))
COINS_DAILY_REWARD = int(os.getenv("COINS_DAILY_REWARD", "100"))
MESSAGE_COOLDOWN_SECONDS = int(os.getenv("MESSAGE_COOLDOWN_SECONDS", "60"))
MIN_VOICE_MINUTES_FOR_REWARD = int(os.getenv("MIN_VOICE_MINUTES_FOR_REWARD", "1"))

# XP System
XP_ENABLED = os.getenv("XP_ENABLED", "true").lower() == "true"
XP_PER_MESSAGE = int(os.getenv("XP_PER_MESSAGE", "10"))
XP_PER_MINUTE_VOICE = int(os.getenv("XP_PER_MINUTE_VOICE", "5"))
XP_LEVEL_MULTIPLIER = int(os.getenv("XP_LEVEL_MULTIPLIER", "100"))  # XP needed = level^2 * multiplier


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def obsidian_embed(
    title: str, 
    desc: str = "", 
    *, 
    color: discord.Color = None,
    author: discord.Member = None,
    author_name: str = None,
    author_icon: str = None,
    thumbnail: str = None,
    image: str = None,
    footer: str = None,
    footer_icon: str = None,
    fields: list = None,
    client: discord.Client = None
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
    """
    # Default to a nice purple-blue color for Obsidian theme
    if color is None:
        color = discord.Color.from_rgb(75, 0, 130)  # Indigo/purple
    
    e = discord.Embed(title=title, description=desc, color=color)
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
    
    # Add fields
    if fields:
        for field in fields:
            if len(field) == 2:
                name, value = field
                inline = False
            else:
                name, value, inline = field
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
            e.set_footer(text="Obsidian Clan Bot", icon_url="https://i.imgur.com/4M34hi2.png")
    
    return e


def get_mod_role(guild: discord.Guild) -> Optional[discord.Role]:
    """Get the moderator role for a guild."""
    return discord.utils.get(guild.roles, name=MOD_ROLE_NAME)


def is_mod(member: discord.Member) -> bool:
    """Check if a member has the moderator role."""
    return any(r.name == MOD_ROLE_NAME for r in member.roles)


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
