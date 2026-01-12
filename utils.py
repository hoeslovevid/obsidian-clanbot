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
MESSAGE_COOLDOWN_SECONDS = int(os.getenv("MESSAGE_COOLDOWN_SECONDS", "60"))


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def obsidian_embed(title: str, desc: str = "", *, color: discord.Color = discord.Color.dark_grey()) -> discord.Embed:
    """Create a standardized Obsidian-themed embed."""
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = now_utc()
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
