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
from core.config import (
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

# Consistent footer for embeds
EMBED_FOOTER_DEFAULT = "Use /help for commands"

# Stable colors by category — custom hex palette for a cohesive Obsidian brand feel
EMBED_COLORS = {
    "economy":    discord.Color.from_str("#F0A800"),  # warm amber gold
    "warframe":   discord.Color.from_str("#4DA6FF"),  # Warframe signature blue
    "moderation": discord.Color.from_str("#E05252"),  # muted red
    "community":  discord.Color.from_str("#52C97B"),  # fresh green
    "general":    discord.Color.from_str("#7C83FF"),  # rich blurple
    "success":    discord.Color.from_str("#43B581"),  # Discord success green
    "warning":    discord.Color.from_str("#FAA61A"),  # amber warning
    "error":      discord.Color.from_str("#F04747"),  # Discord error red
    "prestige":   discord.Color.from_str("#C084FC"),  # purple for milestones/level-ups
}

# Common time phrases for autocomplete (event_create, reminder, etc.)
TIME_AUTOCOMPLETE_CHOICES = [
    ("in 1 hour", "1 hour from now"),
    ("in 2 hours", "2 hours from now"),
    ("in 30 minutes", "30 min from now"),
    ("tomorrow 8pm", "Tomorrow at 8 PM"),
    ("tomorrow 9am", "Tomorrow at 9 AM"),
    ("next Monday 7pm", "Next Monday 7 PM"),
    ("in 1 day", "1 day from now"),
]


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


def success_embed(title: str, message: str, *, flair: Optional[str] = None, client=None, **kwargs) -> discord.Embed:
    """Consistent success embed with optional celebratory flair."""
    desc = truncate_desc(str(message))
    if flair:
        desc += f"\n\n_{flair}_"
    return obsidian_embed(
        f"✅ {title}" if not title.startswith("✅") else title,
        desc,
        category="success",
        footer=EMBED_FOOTER_DEFAULT,
        client=client,
        **kwargs
    )


async def try_dm_then_ephemeral(
    user: discord.User,
    embed: discord.Embed,
    interaction: discord.Interaction,
    ephemeral_message: str = "I couldn't DM you (DMs may be closed). Here's the info:",
) -> bool:
    """Try to DM the user; if that fails, send ephemeral reply with original embed. Returns True if DMed, False if ephemeral fallback."""
    try:
        await user.send(embed=embed)
        if not interaction.response.is_done():
            await interaction.response.send_message("Check your DMs!", ephemeral=True)
        else:
            await interaction.followup.send("Check your DMs!", ephemeral=True)
        return True
    except (discord.Forbidden, discord.HTTPException):
        fallback = embed.copy()
        if fallback.description:
            fallback.description = f"{ephemeral_message}\n\n{fallback.description}"
        else:
            fallback.description = ephemeral_message
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=fallback, ephemeral=True)
        else:
            await interaction.followup.send(embed=fallback, ephemeral=True)
        return False


def feature_off_embed(feature: str, action_hint: Optional[str] = None, client=None) -> discord.Embed:
    """Consistent embed when a feature is disabled."""
    msg = f"**{feature}** is currently disabled."
    return error_embed("Feature Disabled", msg, action_hint=(action_hint or "Ask a moderator to enable it."), client=client)


def bullet_list(items: list[str], bullet: str = "•") -> str:
    """Format items as a bullet list (mobile-friendly)."""
    return "\n".join(f"{bullet} {item}" for item in items if item)


def format_number(n: int) -> str:
    """Format number with commas (e.g. 1,234,567)."""
    return f"{n:,}"


def pluralize(n: int, singular: str, plural: Optional[str] = None) -> str:
    """Return singular or plural form. plural defaults to singular + 's'."""
    if plural is None:
        plural = singular + "s"
    return singular if n == 1 else plural


def format_duration_friendly(seconds: float) -> str:
    """Format seconds as friendly duration (e.g. '4h 23m', '12m 5s')."""
    if seconds <= 0:
        return "now"
    total = int(seconds)
    days = total // 86400
    hours = (total % 86400) // 3600
    mins = (total % 3600) // 60
    secs = total % 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or (days or hours):
        parts.append(f"{mins}m")
    elif secs:
        parts.append(f"{secs}s")
    return " ".join(parts) if parts else "< 1m"


def error_embed(title: str, message: str, *, action_hint: Optional[str] = None, client=None) -> discord.Embed:
    """Consistent error embed format with optional actionable next step."""
    desc = truncate_desc(str(message))
    if action_hint:
        desc += f"\n\n_→ {action_hint}_"
    return obsidian_embed(
        f"❌ {title}" if not title.startswith("❌") else title,
        desc,
        category="error",
        footer=EMBED_FOOTER_DEFAULT,
        client=client,
    )


_THREAD_NAME_MAX = 100


def format_thread_name(
    case_id: str,
    user: discord.abc.User,
    category: str,
    created_iso: str,
) -> str:
    """Build a Discord thread name for complaint/docket staff threads (max 100 chars)."""
    _ = created_iso  # Caller passes for auditing; visible name stays human-readable
    cid = str(case_id).strip()[:34]
    who = (" ".join(str(getattr(user, "display_name", None) or user.name).split())[:26] or "user")
    cat = " ".join(str(category or "").split())[:38]
    if cat:
        name = f"{cid} · {cat} · {who}"
    else:
        name = f"{cid} · {who}"
    if len(name) > _THREAD_NAME_MAX:
        name = name[: _THREAD_NAME_MAX - 1] + "…"
    return name


def dm_blocked_help_embed(
    title: str,
    description: str,
    *,
    client: Optional[discord.Client] = None,
) -> discord.Embed:
    """Embed when a DM-only flow fails because the user's DMs are closed."""
    ttl = title if title.startswith(("📭", "📬")) else f"📭 {title}"
    return obsidian_embed(
        ttl,
        str(description),
        category="warning",
        footer="Enable DMs from server members under User Settings → Privacy & Safety.",
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
    category: Optional[str] = None,
    author: Optional[discord.abc.User] = None,
    author_name: Optional[str] = None,
    author_icon: Optional[str] = None,
    thumbnail: Optional[str] = None,
    image: Optional[str] = None,
    footer: Optional[str] = None,
    footer_icon: Optional[str] = None,
    fields: Optional[list] = None,
    client: Optional[discord.Client] = None,
    timestamp: bool = True,
) -> discord.Embed:
    """Create a standardized Obsidian-themed embed.

    Args:
        title:       Embed title.
        desc:        Embed description.
        color:       Explicit embed color (overrides category).
        category:    Key from EMBED_COLORS for auto-color ("economy", "warframe", etc.).
        author:      Discord member shown as embed author (avatar + display name).
        author_name: Custom author name (used when author member not available).
        author_icon: Custom author icon URL.
        thumbnail:   Thumbnail image URL (top-right corner).
        image:       Large banner image URL (bottom of embed).
        footer:      Custom footer text.
        footer_icon: Custom footer icon URL (defaults to bot avatar when client given).
        fields:      List of (name, value) or (name, value, inline) tuples.
        client:      Bot client — enables bot-avatar thumbnail and footer icon.
        timestamp:   Whether to include current UTC timestamp (default True).
    """
    # Resolve color: explicit > category > default brand color
    if color is None:
        color = EMBED_COLORS.get(category or "", EMBED_COLORS["general"])
    
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
    
    # Set thumbnail (default to bot avatar for help/success when client provided)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    elif client and client.user:
        bot_avatar = client.user.display_avatar.url if hasattr(client.user, "display_avatar") else (client.user.avatar.url if client.user.avatar else None)
        if bot_avatar:
            e.set_thumbnail(url=bot_avatar)
    
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
    
    # Resolve bot avatar for footer icon (used when no explicit footer_icon given)
    _bot_avatar: Optional[str] = None
    if client and client.user:
        _bot_avatar = (
            client.user.display_avatar.url
            if hasattr(client.user, "display_avatar")
            else (client.user.avatar.url if client.user.avatar else None)
        )

    # Set footer: always attach bot avatar as icon for a polished look
    footer_text = footer or EMBED_FOOTER_DEFAULT
    e.set_footer(text=footer_text[:2048], icon_url=footer_icon or _bot_avatar)
    
    return e


# --- Member-facing QoL (buttons, DMs, Warframe API) ---
BUTTON_ONLY_RUNNER_MSG = (
    "These buttons are for whoever ran the command. "
    "Run the same slash command yourself if you need this. _(Only you can see this.)_"
)

DM_SETTINGS_HINT = (
    "**To receive bot DMs:** right-click this server → **Privacy Settings** → turn on **Direct Messages** "
    "from server members, then try again."
)


def warframe_data_unavailable_embed(client=None) -> discord.Embed:
    """Friendly message when api.warframestat.us is down, slow, or flaky."""
    return obsidian_embed(
        "Can't load live data right now",
        "Warframe's public stats service is often slow or briefly offline—that's normal, not your fault. "
        "Wait a minute and try again, or tap **Try again** / **Update data** if you see those buttons.\n\n"
        "_If we're showing cached data, countdowns might be slightly off._",
        color=discord.Color.orange(),
        client=client,
    )


def dm_blocked_help_embed(title: str, what_failed: str, client=None) -> discord.Embed:
    """Explain that DMs failed and how to enable them."""
    return obsidian_embed(
        title,
        f"{what_failed}\n\n{DM_SETTINGS_HINT}",
        color=discord.Color.orange(),
        client=client,
    )


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


def copy_friendly_id(raw_id: int) -> str:
    """Format ID for easy copy-paste (backtick-wrapped, no spaces)."""
    return f"`{raw_id}`"


def permission_hint_embed(missing: str, *, client=None) -> discord.Embed:
    """Actionable embed when bot lacks a permission."""
    hints = {
        "manage_messages": "Ask an admin to grant **Manage Messages** in this channel.",
        "manage_channels": "Ask an admin to grant **Manage Channels**.",
        "send_messages": "Ask an admin to allow **Send Messages** here.",
        "manage_roles": "Ask an admin to place my role above the target role.",
        "kick_members": "Ask an admin to grant **Kick Members**.",
        "ban_members": "Ask an admin to grant **Ban Members**.",
    }
    hint = hints.get(missing.lower().replace(" ", "_"), "Ask an administrator to grant the required permission.")
    return error_embed("Missing Permission", f"I need **{missing.replace('_', ' ').title()}** to do that.", action_hint=hint, client=client)


def see_also_footer(*commands: str) -> str:
    """Build 'See also' footer hint from command paths."""
    if not commands:
        return ""
    return f"See also: " + ", ".join(f"`/{c}`" for c in commands)


async def send_levelup_announcement(
    guild: discord.Guild,
    member: discord.Member,
    level: int,
    xp: int,
    total_xp: int,
) -> bool:
    """
    Send a level-up announcement embed to the configured channel, or DM the user
    if they have opted in to private level-up notifications.
    Returns True if sent, False otherwise.
    """
    from database import get_guild_setting, xp_for_level, xp_for_next_level

    xp_needed_for_level = xp_for_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
    xp_for_next = xp_for_next_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
    xp_in_current_level = xp - xp_needed_for_level
    xp_needed_in_level = xp_for_next - xp_needed_for_level
    progress_pct = min(100, int(100 * xp_in_current_level / xp_needed_in_level)) if xp_needed_in_level > 0 else 100

    fields = [
        ("⭐ Level", f"**{level}**", True),
        ("📊 XP", f"{xp:,} / {xp_for_next:,}", True),
        ("Progress", render_bar(progress_pct), False),
    ]

    # Check if user prefers a private DM over a public announcement
    dm_pref = await get_guild_setting(guild.id, f"user_levelup_dm:{member.id}")
    if dm_pref == "1":
        embed = obsidian_embed(
            "🎉 Level Up!",
            f"You leveled up to **Level {level}** in **{guild.name}**!\n\n"
            f"-# Keep chatting and staying active to climb even higher!",
            category="prestige",
            author=member,
            thumbnail=member.display_avatar.url if member.display_avatar else None,
            image=LEVELUP_IMAGE_URL,
            fields=fields,
            footer=f"Total XP: {total_xp:,}",
            client=None,
        )
        try:
            await member.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.debug(f"Could not DM level-up to {member}: {e}")
            # Fall through to channel announcement if DM fails

    channel_id_str = await get_guild_setting(guild.id, XP_LEVELUP_CHANNEL_KEY)
    if not channel_id_str or not channel_id_str.isdigit():
        return False

    channel = guild.get_channel(int(channel_id_str))
    if not isinstance(channel, discord.abc.Messageable):
        return False

    embed = obsidian_embed(
        "🎉 Level Up!",
        f"{member.mention} has leveled up to **Level {level}**!\n\n"
        f"-# Keep chatting and staying active to climb even higher!",
        category="prestige",
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


def render_bar(pct: float, length: int = 12, *, show_pct: bool = True) -> str:
    """Render a sleek Unicode progress bar for Discord embeds.

    Uses ▰ (filled) and ▱ (empty) for a clean, modern look consistent
    across all bot commands.

    Args:
        pct:      Percentage 0–100 (clamped automatically).
        length:   Number of segments (default 12).
        show_pct: Whether to append the percentage label.

    Returns:
        e.g. "▰▰▰▰▰▰▰▱▱▱▱▱ · 58%"
    """
    pct = min(100.0, max(0.0, float(pct)))
    filled = round(pct / 100 * length)
    bar = "▰" * filled + "▱" * (length - filled)
    if show_pct:
        return f"{bar} · **{pct:.0f}%**"
    return bar


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


def setup_missing_embed(
    feature: str,
    fix_command: str,
    extra: str = "",
    client: Optional[discord.Client] = None,
) -> discord.Embed:
    """Return a standardised 'feature not configured' embed that tells mods the exact fix.

    Args:
        feature:     Human-readable feature name, e.g. "Events channel".
        fix_command: The slash command mods should run, e.g. "/general setup_obsidian".
        extra:       Optional additional context shown in a second line.
        client:      Bot client (used for thumbnail/branding).
    """
    desc = (
        f"**{feature}** has not been configured for this server.\n\n"
        f"🔧 **Mods:** run `{fix_command}` to set it up."
    )
    if extra:
        desc += f"\n\n_{extra}_"
    return obsidian_embed(
        f"⚙️ {feature} Not Configured",
        desc,
        color=discord.Color.orange(),
        footer=f"Run {fix_command} to enable this feature",
        client=client,
    )
