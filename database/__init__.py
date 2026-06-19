"""
Database package — runtime helpers for every feature area.

Layout
------
database/__init__.py   All runtime helper functions (settings, economy, XP,
                       moderation, Warframe roles, etc.)  ~1 300 lines
database/schema.py     init_db() — every CREATE TABLE, migration and index
                       statement (~1 600 lines of DDL, kept separate so the
                       runtime helpers are easy to navigate)

Usage
-----
All existing callers continue to use::

    from database import add_xp, get_guild_setting, init_db

The package __init__ re-exports everything so the import surface is unchanged.
"""
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Any
import aiosqlite  # type: ignore

# Lazy import discord to avoid circular dependencies
try:
    import discord  # type: ignore
except ImportError:
    discord = None  # type: ignore

# Use config for DB_PATH (single source of truth)
from core.config import DB_PATH
from core.db import open_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory settings cache
# ---------------------------------------------------------------------------
# guild_settings is read on almost every command (incident mode, channel IDs,
# feature flags). Opening a new aiosqlite connection for each call wastes
# hundreds of file-descriptor cycles per minute.  A 5-minute TTL cache drops
# DB churn by ~80 % while keeping values fresh enough for all use-cases.
#
# Cache layout:  _settings_cache["{guild_id}:{key}"] = (value_or_None, mono_ts)
_SETTINGS_CACHE: dict[str, tuple[Optional[str], float]] = {}
_SETTINGS_TTL: float = 300.0   # seconds


def _settings_key(guild_id: int, key: str) -> str:
    return f"{guild_id}:{key}"


def _cache_get(guild_id: int, key: str) -> tuple[bool, Optional[str]]:
    """Return (hit, value). hit=False means cache miss or expired."""
    ck = _settings_key(guild_id, key)
    entry = _SETTINGS_CACHE.get(ck)
    if entry is None:
        return False, None
    value, ts = entry
    if time.monotonic() - ts > _SETTINGS_TTL:
        del _SETTINGS_CACHE[ck]
        return False, None
    return True, value


def _cache_put(guild_id: int, key: str, value: Optional[str]) -> None:
    _SETTINGS_CACHE[_settings_key(guild_id, key)] = (value, time.monotonic())


def _cache_invalidate(guild_id: int, key: str) -> None:
    _SETTINGS_CACHE.pop(_settings_key(guild_id, key), None)


def invalidate_guild_settings_cache(guild_id: Optional[int] = None) -> None:
    """Evict cached settings for a guild, or the entire cache if guild_id is None."""
    if guild_id is None:
        _SETTINGS_CACHE.clear()
    else:
        prefix = f"{guild_id}:"
        for k in list(_SETTINGS_CACHE.keys()):
            if k.startswith(prefix):
                del _SETTINGS_CACHE[k]


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


# --------------------- Guild Settings ---------------------
async def get_guild_setting(guild_id: int, key: str) -> Optional[str]:
    """Get a guild setting value (cached, 5-min TTL)."""
    hit, cached = _cache_get(guild_id, key)
    if hit:
        return cached
    async with open_db() as db:
        cur = await db.execute(
            "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        )
        row = await cur.fetchone()
        value = row[0] if row else None
    _cache_put(guild_id, key, value)
    return value


async def get_configured_channel_id(guild_id: int, setting_key: str) -> Optional[int]:
    """
    Get channel ID from guild_settings only (no env fallback, no auto-create).
    Returns None if not configured or explicitly skipped (stored as "0").
    Use this to check if a channel is configured before allowing channel-dependent commands.
    """
    val = await get_guild_setting(guild_id, setting_key)
    if not val or val == "0" or val.lower() == "skipped":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


async def set_guild_setting(guild_id: int, key: str, value: str) -> None:
    """Set a guild setting value and immediately invalidate the cache entry."""
    _cache_invalidate(guild_id, key)
    try:
        from core.channels import invalidate_channel_resolve_cache

        invalidate_channel_resolve_cache(guild_id, key)
    except Exception:
        pass
    async with open_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)",
            (guild_id, key, value),
        )
        await db.commit()
    _cache_put(guild_id, key, value)


async def delete_guild_setting(guild_id: int, key: str) -> None:
    """Remove a guild_setting row if present."""
    _cache_invalidate(guild_id, key)
    async with open_db() as db:
        await db.execute(
            "DELETE FROM guild_settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        )
        await db.commit()


_BARO_HASH_KEY = "baro_inventory_hash"


async def get_baro_inventory_hash(guild_id: int) -> Optional[str]:
    """Last-seen Baro inventory hash for new-item markers (per guild)."""
    return await get_guild_setting(guild_id, _BARO_HASH_KEY)


async def set_baro_inventory_hash(guild_id: int, hash_val: str) -> None:
    """Persist Baro inventory hash after a visit is displayed."""
    await set_guild_setting(guild_id, _BARO_HASH_KEY, hash_val)


async def record_command_usage(guild_id: int, user_id: int, command_name: str, weekday: int) -> None:
    """Bump the per-user / per-command / per-weekday counter used by /tools my_stats.

    Aggregated by ``(guild_id, user_id, command_name, weekday)`` so the table
    stays small even for very active servers — at most 7 rows per command
    per user.
    """
    if not command_name:
        return
    weekday = max(0, min(6, int(weekday)))
    now_iso = now_utc().isoformat()
    async with open_db() as db:
        await db.execute(
            """
            INSERT INTO command_usage_stats (guild_id, user_id, command_name, weekday, count, last_used_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id, command_name, weekday)
            DO UPDATE SET count = count + 1, last_used_at = excluded.last_used_at
            """,
            (guild_id, user_id, command_name, weekday, now_iso),
        )
        await db.commit()


async def get_user_command_stats(guild_id: int, user_id: int, *, top_n: int = 10) -> dict:
    """Return aggregated command-usage stats for ``user_id`` in this guild.

    Shape: ``{"top": [(command, count), …], "total": int, "by_weekday": [int]*7,
    "first_used": iso_or_None, "last_used": iso_or_None}``.
    """
    async with open_db() as db:
        cur = await db.execute(
            """
            SELECT command_name, SUM(count) AS total
            FROM command_usage_stats
            WHERE guild_id=? AND user_id=?
            GROUP BY command_name
            ORDER BY total DESC
            LIMIT ?
            """,
            (guild_id, user_id, max(1, int(top_n))),
        )
        top = [(r[0], int(r[1] or 0)) for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT COALESCE(SUM(count),0) FROM command_usage_stats WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        total_row = await cur.fetchone()
        total = int(total_row[0] or 0) if total_row else 0

        cur = await db.execute(
            """
            SELECT weekday, COALESCE(SUM(count),0)
            FROM command_usage_stats
            WHERE guild_id=? AND user_id=?
            GROUP BY weekday
            """,
            (guild_id, user_id),
        )
        weekday_counts = [0] * 7
        for wd, cnt in await cur.fetchall():
            wd = max(0, min(6, int(wd)))
            weekday_counts[wd] = int(cnt or 0)

        cur = await db.execute(
            "SELECT MIN(last_used_at), MAX(last_used_at) FROM command_usage_stats WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        ts_row = await cur.fetchone()
        first_used = ts_row[0] if ts_row else None
        last_used = ts_row[1] if ts_row else None

    return {
        "top": top,
        "total": total,
        "by_weekday": weekday_counts,
        "first_used": first_used,
        "last_used": last_used,
    }


async def get_user_timezone(guild_id: int, user_id: int) -> Optional[str]:
    """Get a user's timezone preference (e.g. America/New_York). Uses guild_settings key 'user_tz:{user_id}'."""
    return await get_guild_setting(guild_id, f"user_tz:{user_id}")


async def set_user_timezone(guild_id: int, user_id: int, timezone: str) -> None:
    """Set a user's timezone preference."""
    await set_guild_setting(guild_id, f"user_tz:{user_id}", timezone)


async def get_user_platform(guild_id: int, user_id: int) -> Optional[str]:
    """Get user's preferred trading platform (pc, xbox, ps4, switch)."""
    val = await get_guild_setting(guild_id, f"user_platform:{user_id}")
    return val if val in ("pc", "xbox", "ps4", "switch") else None


async def set_user_platform(guild_id: int, user_id: int, platform: str) -> None:
    """Set user's preferred trading platform."""
    await set_guild_setting(guild_id, f"user_platform:{user_id}", platform)


async def get_quieter_mode(guild_id: int) -> bool:
    """Whether the guild has quieter mode enabled (mutes non-essential pings)."""
    val = await get_guild_setting(guild_id, "quieter_mode")
    return val == "1"


async def set_quieter_mode(guild_id: int, enabled: bool) -> None:
    """Enable or disable quieter mode for the guild."""
    await set_guild_setting(guild_id, "quieter_mode", "1" if enabled else "0")


async def get_digest_dm(guild_id: int, user_id: int) -> bool:
    """Whether the user opted into the daily DM digest."""
    val = await get_guild_setting(guild_id, f"user_digest_dm:{user_id}")
    return val == "1"


async def set_digest_dm(guild_id: int, user_id: int, enabled: bool) -> None:
    """Enable or disable daily DM digest for a user."""
    await set_guild_setting(guild_id, f"user_digest_dm:{user_id}", "1" if enabled else "0")


async def get_achievement_notify_style(guild_id: int, user_id: int) -> str:
    """Return achievement notify style: ephemeral, channel, dm, or off."""
    style = await get_guild_setting(guild_id, f"user_achievement_notify_style:{user_id}")
    if style in ("ephemeral", "channel", "dm", "off"):
        return style
    legacy = await get_guild_setting(guild_id, f"user_achievement_notify:{user_id}")
    if legacy == "0":
        return "off"
    return "ephemeral"


async def set_achievement_notify_style(guild_id: int, user_id: int, style: str) -> None:
    """Set achievement notification style (ephemeral/channel/dm/off)."""
    normalized = style if style in ("ephemeral", "channel", "dm", "off") else "ephemeral"
    await set_guild_setting(guild_id, f"user_achievement_notify_style:{user_id}", normalized)
    await set_guild_setting(
        guild_id,
        f"user_achievement_notify:{user_id}",
        "0" if normalized == "off" else "1",
    )


async def get_log_channel_id(guild_id: int, log_type: str) -> Optional[int]:
    """Get the channel ID for a log type, or None if not configured."""
    async with open_db() as db:
        cur = await db.execute(
            "SELECT channel_id FROM log_channels WHERE guild_id=? AND log_type=? AND enabled=1",
            (guild_id, log_type),
        )
        row = await cur.fetchone()
        return row[0] if row else None


# --------------------- Economy Functions ---------------------
async def get_user_balance(guild_id: int, user_id: int) -> int:
    """Get a user's coin balance."""
    async with open_db() as db:
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def add_coins(guild_id: int, user_id: int, amount: int, transaction_type: str, description: Optional[str] = None) -> None:
    """Add coins to a user's balance. Applies active coin boosts (not to gambling winnings)."""
    # Apply coin boost if active (only for earning, not for shop rewards or gambling winnings)
    _no_boost_types = {"SHOP_REWARD", "GAMBLING", "SHOP_PURCHASE"}
    if transaction_type not in _no_boost_types:
        try:
            boost_val = await get_guild_setting(guild_id, f"coin_boost:{user_id}")
            if boost_val:
                from datetime import datetime, timezone as _tz
                mult_str, exp_str = boost_val.split(":", 1)
                expires = datetime.fromisoformat(exp_str)
                if datetime.now(_tz.utc) < expires:
                    amount = int(amount * float(mult_str))
        except Exception:
            pass
    async with open_db() as db:
        # Insert or update balance
        await db.execute("""
            INSERT INTO user_balances (guild_id, user_id, balance, total_earned)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                balance = balance + ?,
                total_earned = total_earned + ?
        """, (guild_id, user_id, amount, amount, amount, amount))
        
        # Log transaction
        desc = description or ""
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, user_id, amount, transaction_type, desc, now_utc().isoformat()))
        
        await db.commit()


async def remove_coins(guild_id: int, user_id: int, amount: int, transaction_type: str, description: Optional[str] = None) -> bool:
    """Remove coins from a user's balance. Returns True if successful."""
    async with open_db() as db:
        # Check balance
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        current_balance = row[0] if row else 0
        
        if current_balance < amount:
            return False
        
        # Remove coins
        await db.execute("""
            UPDATE user_balances SET balance = balance - ? WHERE guild_id=? AND user_id=?
        """, (amount, guild_id, user_id))
        
        # Log transaction
        desc = description or ""
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, user_id, -amount, transaction_type, desc, now_utc().isoformat()))
        
        await db.commit()
        return True


async def transfer_coins(guild_id: int, from_user_id: int, to_user_id: int, amount: int) -> bool:
    """Transfer coins between users. Returns True if successful."""
    if amount <= 0 or from_user_id == to_user_id:
        return False
    
    async with open_db() as db:
        # Check sender balance
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (guild_id, from_user_id),
        )
        row = await cur.fetchone()
        sender_balance = row[0] if row else 0
        
        if sender_balance < amount:
            return False
        
        # Remove from sender
        await db.execute("""
            UPDATE user_balances SET balance = balance - ? WHERE guild_id=? AND user_id=?
        """, (amount, guild_id, from_user_id))
        
        # Add to receiver
        await db.execute("""
            INSERT INTO user_balances (guild_id, user_id, balance, total_earned)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = balance + ?
        """, (guild_id, to_user_id, amount, 0, amount))
        
        # Log transactions
        now = now_utc().isoformat()
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, from_user_id, -amount, "TRANSFER_OUT", f"Transferred to user {to_user_id}", now))
        
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, to_user_id, amount, "TRANSFER_IN", f"Received from user {from_user_id}", now))
        
        await db.commit()
        return True


# --------------------- XP Functions ---------------------
def calculate_level(xp: int, multiplier: int = 100, exponent: float = 2.25) -> int:
    """Calculate level from XP. Formula: XP = level^exponent * multiplier"""
    if xp <= 0:
        return 0
    import math
    level = int((xp / multiplier) ** (1 / exponent))
    return max(0, level)


def xp_for_level(level: int, multiplier: int = 100, exponent: float = 2.25) -> int:
    """Calculate XP needed for a specific level. Higher exponent = more XP required at high levels."""
    return int(level ** exponent * multiplier)


def xp_for_next_level(current_level: int, multiplier: int = 100, exponent: float = 2.25) -> int:
    """Calculate XP needed to reach the next level."""
    return xp_for_level(current_level + 1, multiplier, exponent)


async def get_user_xp(guild_id: int, user_id: int) -> Tuple[int, int, int]:
    """Get a user's XP, level, and total XP. Returns (xp, level, total_xp)."""
    from core.utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT
    async with open_db() as db:
        cur = await db.execute(
            "SELECT xp, level, total_xp FROM user_xp WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        if row:
            xp, level, total_xp = row
            # Recalculate level in case XP changed
            actual_level = calculate_level(xp, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
            if actual_level != level:
                # Update level if it changed
                await db.execute(
                    "UPDATE user_xp SET level=? WHERE guild_id=? AND user_id=?",
                    (actual_level, guild_id, user_id),
                )
                await db.commit()
                return (xp, actual_level, total_xp)
            return (xp, level, total_xp)
        return (0, 0, 0)


async def add_xp(guild_id: int, user_id: int, amount: int, source: str = "ACTIVITY") -> bool:
    """Add XP to a user. Returns True if user leveled up. Applies active XP boosts."""
    from core.utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT
    # Apply XP boost if active
    try:
        boost_val = await get_guild_setting(guild_id, f"xp_boost:{user_id}")
        if boost_val:
            from datetime import datetime, timezone as _tz
            mult_str, exp_str = boost_val.split(":", 1)
            expires = datetime.fromisoformat(exp_str)
            if datetime.now(_tz.utc) < expires:
                amount = int(amount * float(mult_str))
    except Exception:
        pass
    async with open_db() as db:
        # Get current XP
        cur = await db.execute(
            "SELECT xp, level, total_xp FROM user_xp WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        
        if row:
            current_xp, current_level, total_xp = row
            new_xp = current_xp + amount
            new_total_xp = total_xp + amount
        else:
            current_xp = 0
            current_level = 0
            new_xp = amount
            new_total_xp = amount
        
        # Calculate new level
        new_level = calculate_level(new_xp, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
        
        # Update or insert
        await db.execute("""
            INSERT INTO user_xp (guild_id, user_id, xp, level, total_xp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                xp = ?,
                level = ?,
                total_xp = ?
        """, (guild_id, user_id, new_xp, new_level, new_total_xp, new_xp, new_level, new_total_xp))
        
        await db.commit()
        
        # Return if user leveled up
        return new_level > current_level


async def remove_xp(guild_id: int, user_id: int, amount: int) -> bool:
    """Remove XP from a user. Returns True if successful, False if insufficient XP."""
    from core.utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT
    if amount <= 0:
        return False
    
    async with open_db() as db:
        # Get current XP
        cur = await db.execute(
            "SELECT xp, level, total_xp FROM user_xp WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        
        if not row:
            return False  # User has no XP
        
        current_xp, current_level, total_xp = row
        
        if current_xp < amount:
            return False  # Insufficient XP
        
        # Calculate new values
        new_xp = max(0, current_xp - amount)
        # Note: total_xp should not decrease (it's a lifetime total)
        new_level = calculate_level(new_xp, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
        
        # Update
        await db.execute("""
            UPDATE user_xp
            SET xp = ?, level = ?
            WHERE guild_id=? AND user_id=?
        """, (new_xp, new_level, guild_id, user_id))
        
        await db.commit()
        return True


# --------------------- Complaint Functions ---------------------
async def log_complaint_action(guild_id: int, case_id: str, actor_id: int, action: str, note: str = "", guild: Optional[Any] = None, bot: Optional[Any] = None):
    """
    Log a complaint action.
    If guild and bot are provided, also sends a notification to the ledger channel.
    """
    async with open_db() as db:
        await db.execute("""
            INSERT INTO complaint_actions (guild_id, case_id, actor_id, action, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, case_id, actor_id, action, note, now_utc().isoformat()))
        await db.commit()
    
    # Optional ledger channel notification (if guild and bot are provided)
    if guild and bot:
        try:
            # Import discord here to ensure it's available
            import discord as discord_module  # type: ignore
            from core.channels import resolve_channel_id
            from core.utils import obsidian_embed
            
            # Get ledger channel ID from bot.py constants
            import os
            COMPLAINTS_LOG_CHANNEL_ID = int(os.getenv("COMPLAINTS_LOG_CHANNEL_ID", "0") or "0")
            COMPLAINTS_LOG_CHANNEL_NAME = os.getenv("COMPLAINTS_LOG_CHANNEL_NAME", "docket-ledger")
            
            ledger_id = await resolve_channel_id(guild, "complaints_log_channel_id", COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME)
            if ledger_id:
                ch = guild.get_channel(ledger_id)
                if ch is not None and isinstance(ch, discord_module.TextChannel):
                    actor = guild.get_member(actor_id)
                    desc = f"**Case:** `{case_id}`\n**Action:** {action}\n**By:** {actor.mention if actor else actor_id}"
                    if note:
                        desc += f"\n**Note:** {note}"
                    await ch.send(embed=obsidian_embed("Docket Ledger", desc, color=discord_module.Color.dark_grey(), client=bot))
        except Exception as e:
            # Don't fail if ledger channel notification fails - just log the database entry
            import logging
            logging.getLogger(__name__).warning(f"Failed to send ledger notification for complaint action: {e}")


# --------------------- Activity Functions ---------------------
async def track_command_usage(guild_id: int, user_id: int):
    """Track that a user used a command."""
    async with open_db() as db:
        now = now_utc()
        today = now.date().isoformat()
        
        # Update or insert activity stats
        await db.execute("""
            INSERT INTO activity_stats (guild_id, user_id, commands_used, last_activity_date, weekly_score, monthly_score)
            VALUES (?, ?, 1, ?, 1, 1)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                commands_used = commands_used + 1,
                last_activity_date = ?,
                weekly_score = weekly_score + 1,
                monthly_score = monthly_score + 1
        """, (guild_id, user_id, today, today))
        
        # Log activity
        await db.execute("""
            INSERT INTO activity_log (guild_id, user_id, activity_type, activity_date, points)
            VALUES (?, ?, 'command', ?, 1)
        """, (guild_id, user_id, now.isoformat()))
        
        await db.commit()


async def track_event_attendance(guild_id: int, user_id: int):
    """Track that a user attended an event."""
    async with open_db() as db:
        now = now_utc()
        today = now.date().isoformat()
        
        # Update or insert activity stats
        await db.execute("""
            INSERT INTO activity_stats (guild_id, user_id, events_attended, last_activity_date, weekly_score, monthly_score)
            VALUES (?, ?, 1, ?, 10, 10)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                events_attended = events_attended + 1,
                last_activity_date = ?,
                weekly_score = weekly_score + 10,
                monthly_score = monthly_score + 10
        """, (guild_id, user_id, today, today))
        
        # Log activity
        await db.execute("""
            INSERT INTO activity_log (guild_id, user_id, activity_type, activity_date, points)
            VALUES (?, ?, 'event', ?, 10)
        """, (guild_id, user_id, now.isoformat()))

        cur = await db.execute(
            "SELECT events_attended FROM activity_stats WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        events_count = row[0] if row else 1

        await db.commit()

        # Event attendance achievements
        try:
            for n, ach_id in [(1, "event_first"), (10, "event_10"), (50, "event_50")]:
                if events_count >= n:
                    await check_and_unlock_achievement(guild_id, user_id, ach_id, None)
        except Exception:
            pass


async def update_activity_voice_minutes(guild_id: int, user_id: int, minutes: int):
    """Update voice minutes in activity stats."""
    async with open_db() as db:
        # Get current voice minutes from voice_activity table
        cur = await db.execute("""
            SELECT SUM(total_minutes) FROM voice_activity
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        total_voice_minutes = row[0] if row and row[0] else 0
        
        # Update activity stats
        today = now_utc().date().isoformat()
        points = minutes // 10  # 1 point per 10 minutes
        
        await db.execute("""
            INSERT INTO activity_stats (guild_id, user_id, voice_minutes, last_activity_date, weekly_score, monthly_score)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                voice_minutes = ?,
                last_activity_date = ?,
                weekly_score = weekly_score + ?,
                monthly_score = monthly_score + ?
        """, (guild_id, user_id, total_voice_minutes, today, points, points, total_voice_minutes, today, points, points))
        
        await db.commit()


async def increment_activity_voice_minutes(guild_id: int, user_id: int, delta_minutes: int) -> int:
    """Increment lifetime voice minutes in ``activity_stats`` (persists after voice sessions end).

    Returns the user's new cumulative ``voice_minutes`` for this guild.
    """
    if delta_minutes <= 0:
        async with open_db() as db:
            cur = await db.execute(
                "SELECT voice_minutes FROM activity_stats WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

    today = now_utc().date().isoformat()
    points = delta_minutes // 10  # mirrors per-minute voice rewards

    async with open_db() as db:
        await db.execute(
            """
            INSERT INTO activity_stats (guild_id, user_id, voice_minutes, last_activity_date, weekly_score, monthly_score)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                voice_minutes = voice_minutes + excluded.voice_minutes,
                last_activity_date = excluded.last_activity_date,
                weekly_score = weekly_score + ?,
                monthly_score = monthly_score + ?
            """,
            (guild_id, user_id, delta_minutes, today, points, points, points, points),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT voice_minutes FROM activity_stats WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else delta_minutes


async def reset_weekly_scores():
    """Reset weekly scores (should be called weekly)."""
    async with open_db() as db:
        await db.execute("UPDATE activity_stats SET weekly_score = 0")
        await db.commit()


async def reset_monthly_scores():
    """Reset monthly scores (should be called monthly)."""
    async with open_db() as db:
        await db.execute("UPDATE activity_stats SET monthly_score = 0")
        await db.commit()


# --------------------- Auto-Moderation Functions ---------------------
async def get_auto_mod_settings(guild_id: int) -> Optional[dict]:
    """Get auto-moderation settings for a guild."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT enabled, spam_enabled, spam_threshold, spam_interval,
                   caps_enabled, caps_threshold, caps_min_length,
                   links_enabled, links_whitelist,
                   mention_enabled, mention_limit,
                   punishment_action, punishment_duration, log_channel_id
            FROM auto_mod_settings WHERE guild_id = ?
        """, (guild_id,))
        row = await cur.fetchone()
        
        if not row:
            return None
        
        return {
            "enabled": bool(row[0]),
            "spam_enabled": bool(row[1]),
            "spam_threshold": row[2],
            "spam_interval": row[3],
            "caps_enabled": bool(row[4]),
            "caps_threshold": row[5],
            "caps_min_length": row[6],
            "links_enabled": bool(row[7]),
            "links_whitelist": row[8] or "",
            "mention_enabled": bool(row[9]),
            "mention_limit": row[10],
            "punishment_action": row[11],
            "punishment_duration": row[12],
            "log_channel_id": row[13]
        }


async def update_auto_mod_settings(guild_id: int, **kwargs):
    """Update auto-moderation settings. Only updates provided fields."""
    # Get existing settings
    existing = await get_auto_mod_settings(guild_id)
    
    # Merge with new values
    if existing:
        existing.update(kwargs)
        settings = existing
    else:
        # Default settings
        defaults = {
            "enabled": True,
            "spam_enabled": True,
            "spam_threshold": 5,
            "spam_interval": 10,
            "caps_enabled": True,
            "caps_threshold": 70,
            "caps_min_length": 10,
            "links_enabled": False,
            "links_whitelist": "",
            "mention_enabled": True,
            "mention_limit": 5,
            "punishment_action": "delete",
            "punishment_duration": None,
            "log_channel_id": None
        }
        defaults.update(kwargs)
        settings = defaults
    
    async with open_db() as db:
        await db.execute("""
            INSERT INTO auto_mod_settings (
                guild_id, enabled, spam_enabled, spam_threshold, spam_interval,
                caps_enabled, caps_threshold, caps_min_length,
                links_enabled, links_whitelist,
                mention_enabled, mention_limit,
                punishment_action, punishment_duration, log_channel_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                enabled = excluded.enabled,
                spam_enabled = excluded.spam_enabled,
                spam_threshold = excluded.spam_threshold,
                spam_interval = excluded.spam_interval,
                caps_enabled = excluded.caps_enabled,
                caps_threshold = excluded.caps_threshold,
                caps_min_length = excluded.caps_min_length,
                links_enabled = excluded.links_enabled,
                links_whitelist = excluded.links_whitelist,
                mention_enabled = excluded.mention_enabled,
                mention_limit = excluded.mention_limit,
                punishment_action = excluded.punishment_action,
                punishment_duration = excluded.punishment_duration,
                log_channel_id = excluded.log_channel_id
        """, (
            guild_id,
            int(settings["enabled"]),
            int(settings["spam_enabled"]),
            settings["spam_threshold"],
            settings["spam_interval"],
            int(settings["caps_enabled"]),
            settings["caps_threshold"],
            settings["caps_min_length"],
            int(settings["links_enabled"]),
            settings["links_whitelist"],
            int(settings["mention_enabled"]),
            settings["mention_limit"],
            settings["punishment_action"],
            settings["punishment_duration"],
            settings["log_channel_id"]
        ))
        await db.commit()


async def log_auto_mod_violation(guild_id: int, user_id: int, violation_type: str, message_content: str, action_taken: str):
    """Log an auto-moderation violation."""
    async with open_db() as db:
        await db.execute("""
            INSERT INTO auto_mod_violations (guild_id, user_id, violation_type, message_content, action_taken, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, user_id, violation_type, message_content[:500], action_taken, now_utc().isoformat()))
        await db.commit()


async def get_spam_tracking(guild_id: int, user_id: int) -> Optional[dict]:
    """Get spam tracking data for a user."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT message_count, first_message_time, last_message_time
            FROM auto_mod_spam_tracking WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        
        if not row:
            return None
        
        return {
            "message_count": row[0],
            "first_message_time": row[1],
            "last_message_time": row[2]
        }


async def update_spam_tracking(guild_id: int, user_id: int, message_count: int, first_message_time: str, last_message_time: str):
    """Update spam tracking for a user."""
    async with open_db() as db:
        await db.execute("""
            INSERT INTO auto_mod_spam_tracking (guild_id, user_id, message_count, first_message_time, last_message_time)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                message_count = excluded.message_count,
                first_message_time = excluded.first_message_time,
                last_message_time = excluded.last_message_time
        """, (guild_id, user_id, message_count, first_message_time, last_message_time))
        await db.commit()


async def reset_spam_tracking(guild_id: int, user_id: int):
    """Reset spam tracking for a user."""
    async with open_db() as db:
        await db.execute("""
            DELETE FROM auto_mod_spam_tracking WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        await db.commit()


# --------------------- Self-Assignable Roles Functions ---------------------
async def add_self_assignable_role(guild_id: int, role_id: int, category: Optional[str] = None, description: Optional[str] = None, max_roles: Optional[int] = None):
    """Add a self-assignable role."""
    async with open_db() as db:
        await db.execute("""
            INSERT INTO self_assignable_roles (guild_id, role_id, category, description, max_roles, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, role_id) DO UPDATE SET
                category = excluded.category,
                description = excluded.description,
                max_roles = excluded.max_roles
        """, (guild_id, role_id, category, description, max_roles, now_utc().isoformat()))
        await db.commit()


async def remove_self_assignable_role(guild_id: int, role_id: int):
    """Remove a self-assignable role."""
    async with open_db() as db:
        await db.execute("""
            DELETE FROM self_assignable_roles WHERE guild_id = ? AND role_id = ?
        """, (guild_id, role_id))
        await db.commit()


async def get_self_assignable_roles(guild_id: int, category: Optional[str] = None) -> list:
    """Get all self-assignable roles for a guild, optionally filtered by category."""
    async with open_db() as db:
        if category:
            cur = await db.execute("""
                SELECT role_id, category, description, max_roles
                FROM self_assignable_roles
                WHERE guild_id = ? AND category = ?
                ORDER BY role_id
            """, (guild_id, category))
        else:
            cur = await db.execute("""
                SELECT role_id, category, description, max_roles
                FROM self_assignable_roles
                WHERE guild_id = ?
                ORDER BY category, role_id
            """, (guild_id,))
        rows = await cur.fetchall()
        return [{"role_id": row[0], "category": row[1], "description": row[2], "max_roles": row[3]} for row in rows]


async def get_self_assignable_categories(guild_id: int) -> list:
    """Get all categories for self-assignable roles."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT DISTINCT category FROM self_assignable_roles
            WHERE guild_id = ? AND category IS NOT NULL
            ORDER BY category
        """, (guild_id,))
        rows = await cur.fetchall()
        return [row[0] for row in rows if row[0]]


async def get_self_assignable_roles_and_categories(guild_id: int) -> tuple[list, list]:
    """Get roles and categories in one connection. Returns (roles_list, categories_list)."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT role_id, category, description, max_roles
            FROM self_assignable_roles
            WHERE guild_id = ?
            ORDER BY category, role_id
        """, (guild_id,))
        rows = await cur.fetchall()
        roles = [{"role_id": row[0], "category": row[1], "description": row[2], "max_roles": row[3]} for row in rows]
        cur2 = await db.execute("""
            SELECT DISTINCT category FROM self_assignable_roles
            WHERE guild_id = ? AND category IS NOT NULL
            ORDER BY category
        """, (guild_id,))
        cat_rows = await cur2.fetchall()
        categories = [r[0] for r in cat_rows if r[0]]
        return (roles, categories)


# --------------------- Level Roles Functions ---------------------
async def add_level_role(guild_id: int, level: int, role_id: int):
    """Add a level role (role assigned at a specific level)."""
    async with open_db() as db:
        await db.execute("""
            INSERT INTO level_roles (guild_id, level, role_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id
        """, (guild_id, level, role_id, now_utc().isoformat()))
        await db.commit()


async def remove_level_role(guild_id: int, level: int):
    """Remove a level role."""
    async with open_db() as db:
        await db.execute("""
            DELETE FROM level_roles WHERE guild_id = ? AND level = ?
        """, (guild_id, level))
        await db.commit()


async def get_level_roles(guild_id: int) -> list:
    """Get all level roles for a guild."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT level, role_id FROM level_roles
            WHERE guild_id = ?
            ORDER BY level ASC
        """, (guild_id,))
        rows = await cur.fetchall()
        return [{"level": row[0], "role_id": row[1]} for row in rows]


async def get_level_role_for_level(guild_id: int, level: int) -> Optional[int]:
    """Get the role ID for a specific level."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT role_id FROM level_roles
            WHERE guild_id = ? AND level = ?
        """, (guild_id, level))
        row = await cur.fetchone()
        return row[0] if row else None


async def get_all_level_roles_up_to(guild_id: int, level: int) -> list:
    """Get all level roles up to and including a specific level."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT level, role_id FROM level_roles
            WHERE guild_id = ? AND level <= ?
            ORDER BY level ASC
        """, (guild_id, level))
        rows = await cur.fetchall()
        return [{"level": row[0], "role_id": row[1]} for row in rows]


# --------------------- Warframe Achievement Roles (Steam playtime, etc.) ---------------------
async def link_steam_account(guild_id: int, user_id: int, steam_id_64: str, warframe_ign: Optional[str] = None):
    """Link a Discord user's Steam account for Warframe playtime tracking."""
    async with open_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO linked_steam_accounts (guild_id, user_id, steam_id_64, warframe_ign, linked_at)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, steam_id_64, warframe_ign, now_utc().isoformat()))
        await db.commit()


async def unlink_steam_account(guild_id: int, user_id: int):
    """Unlink a user's Steam account."""
    async with open_db() as db:
        await db.execute(
            "DELETE FROM linked_steam_accounts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.commit()


async def get_linked_steam_id(guild_id: int, user_id: int) -> Optional[str]:
    """Get linked Steam 64 ID for a user, or None."""
    async with open_db() as db:
        cur = await db.execute(
            "SELECT steam_id_64 FROM linked_steam_accounts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def get_all_linked_steam_accounts(guild_id: int) -> list:
    """Get all (user_id, steam_id_64) for a guild."""
    async with open_db() as db:
        cur = await db.execute(
            "SELECT user_id, steam_id_64 FROM linked_steam_accounts WHERE guild_id=?",
            (guild_id,),
        )
        return await cur.fetchall()


async def update_steam_playtime(guild_id: int, user_id: int, hours: int):
    """Update stored playtime and last checked time."""
    async with open_db() as db:
        await db.execute("""
            UPDATE linked_steam_accounts
            SET last_playtime_hours=?, last_checked_at=?
            WHERE guild_id=? AND user_id=?
        """, (hours, now_utc().isoformat(), guild_id, user_id))
        await db.commit()


async def add_warframe_achievement_role(guild_id: int, achievement_type: str, threshold_value: int, role_id: int):
    """Add a role to assign when user reaches a playtime threshold."""
    async with open_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO warframe_achievement_roles (guild_id, achievement_type, threshold_value, role_id)
            VALUES (?, ?, ?, ?)
        """, (guild_id, achievement_type, threshold_value, role_id))
        await db.commit()


async def remove_warframe_achievement_role(guild_id: int, achievement_type: str, threshold_value: int):
    """Remove a warframe achievement role."""
    async with open_db() as db:
        await db.execute("""
            DELETE FROM warframe_achievement_roles
            WHERE guild_id=? AND achievement_type=? AND threshold_value=?
        """, (guild_id, achievement_type, threshold_value))
        await db.commit()


async def get_warframe_achievement_roles(guild_id: int) -> list:
    """Get all warframe achievement role configs: (achievement_type, threshold_value, role_id)."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT achievement_type, threshold_value, role_id
            FROM warframe_achievement_roles WHERE guild_id=?
            ORDER BY achievement_type, threshold_value
        """, (guild_id,))
        return await cur.fetchall()


async def record_warframe_achievement_unlock(guild_id: int, user_id: int, achievement_type: str, threshold_value: int):
    """Record that a user has been assigned a role for this achievement."""
    async with open_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO warframe_achievement_unlocks
            (guild_id, user_id, achievement_type, threshold_value, unlocked_at)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, achievement_type, threshold_value, now_utc().isoformat()))
        await db.commit()


async def has_warframe_achievement_unlock(guild_id: int, user_id: int, achievement_type: str, threshold_value: int) -> bool:
    """Check if user has already received this achievement role."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT 1 FROM warframe_achievement_unlocks
            WHERE guild_id=? AND user_id=? AND achievement_type=? AND threshold_value=?
        """, (guild_id, user_id, achievement_type, threshold_value))
        return await cur.fetchone() is not None


# --------------------- AFK Functions ---------------------
async def set_afk(guild_id: int, user_id: int, reason: Optional[str] = None):
    """Set a user as AFK."""
    async with open_db() as db:
        await db.execute("""
            INSERT INTO afk_users (guild_id, user_id, reason, set_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                reason = excluded.reason,
                set_at = excluded.set_at
        """, (guild_id, user_id, reason, now_utc().isoformat()))
        await db.commit()


async def remove_afk(guild_id: int, user_id: int):
    """Remove a user's AFK status."""
    async with open_db() as db:
        await db.execute("""
            DELETE FROM afk_users WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        await db.commit()


async def get_afk_status(guild_id: int, user_id: int) -> Optional[dict]:
    """Get a user's AFK status."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT reason, set_at FROM afk_users
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            return {"reason": row[0], "set_at": row[1]}
        return None


# --------------------- Server Stats Functions ---------------------
async def set_server_stats_channel(guild_id: int, channel_id: int, stats_type: str = "members"):
    """Set the server stats channel."""
    async with open_db() as db:
        await db.execute("""
            INSERT INTO server_stats_channels (guild_id, channel_id, stats_type, enabled)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                stats_type = excluded.stats_type,
                enabled = 1
        """, (guild_id, channel_id, stats_type))
        await db.commit()


async def remove_server_stats_channel(guild_id: int):
    """Remove the server stats channel."""
    async with open_db() as db:
        await db.execute("""
            UPDATE server_stats_channels SET enabled = 0 WHERE guild_id = ?
        """, (guild_id,))
        await db.commit()


async def get_server_stats_channel(guild_id: int) -> Optional[dict]:
    """Get the server stats channel settings."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT channel_id, stats_type, enabled FROM server_stats_channels
            WHERE guild_id = ?
        """, (guild_id,))
        row = await cur.fetchone()
        if row and row[2]:  # enabled
            return {"channel_id": row[0], "stats_type": row[1], "enabled": bool(row[2])}
        return None


# --------------------- Milestone Functions ---------------------
async def check_and_record_milestone(guild_id: int, user_id: int, milestone_type: str, milestone_value: int) -> bool:
    """Check if milestone should be recorded and record it. Returns True if milestone was newly achieved."""
    async with open_db() as db:
        # Atomic insert — avoids UNIQUE races when many messages arrive at once.
        cur = await db.execute("""
            INSERT OR IGNORE INTO member_milestones (guild_id, user_id, milestone_type, milestone_value, achieved_at, notified)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (guild_id, user_id, milestone_type, milestone_value, now_utc().isoformat()))
        await db.commit()
        return cur.rowcount > 0


# --------------------- Achievement Functions ---------------------
async def check_and_unlock_achievement(
    guild_id: int,
    user_id: int,
    achievement_id: str,
    bot: Optional[Any] = None,
    interaction: Optional[Any] = None,
) -> bool:
    """Check if achievement should be unlocked and unlock it.

    Returns True if the achievement was newly unlocked.
    When *interaction* is provided and the achievement is newly unlocked, an
    ephemeral embed is sent to the user via interaction.followup.send().
    """
    async with open_db() as db:
        # Check if already unlocked
        cur = await db.execute("""
            SELECT 1 FROM achievements
            WHERE guild_id=? AND user_id=? AND achievement_id=?
        """, (guild_id, user_id, achievement_id))
        if await cur.fetchone():
            return False  # Already unlocked

        # Fetch full achievement definition (name, description, rewards, optional title)
        try:
            cur = await db.execute("""
                SELECT name, description, reward_coins, reward_xp, unlock_title_id
                FROM achievement_definitions WHERE achievement_id=?
            """, (achievement_id,))
            row = await cur.fetchone()
        except Exception:
            # Older DB without unlock_title_id column — fall back to legacy schema.
            cur = await db.execute("""
                SELECT name, description, reward_coins, reward_xp FROM achievement_definitions
                WHERE achievement_id=?
            """, (achievement_id,))
            row = await cur.fetchone()
            row = (row[0], row[1], row[2], row[3], None) if row else None

        ach_name         = row[0] if row else achievement_id.replace("_", " ").title()
        ach_description  = row[1] if row else ""
        reward_coins     = row[2] if row else 0
        reward_xp        = row[3] if row else 0
        unlock_title_id  = row[4] if row and len(row) > 4 else None

        # Unlock achievement
        await db.execute("""
            INSERT INTO achievements (guild_id, user_id, achievement_id, unlocked_at)
            VALUES (?, ?, ?, ?)
        """, (guild_id, user_id, achievement_id, now_utc().isoformat()))

        # Grant linked badge if one exists
        cur = await db.execute("SELECT 1 FROM badge_definitions WHERE badge_id=?", (achievement_id,))
        if await cur.fetchone():
            await db.execute("""
                INSERT OR IGNORE INTO user_badges (guild_id, user_id, badge_id, unlocked_at, is_equipped)
                VALUES (?, ?, ?, ?, 0)
            """, (guild_id, user_id, achievement_id, now_utc().isoformat()))

        await db.commit()

        # Award rewards
        if reward_coins > 0:
            await add_coins(guild_id, user_id, reward_coins, "ACHIEVEMENT", f"Achievement: {achievement_id}")
        if reward_xp > 0:
            await add_xp(guild_id, user_id, reward_xp, f"ACHIEVEMENT_{achievement_id}")

        # Item 107 — auto-unlock paired title (and equip if user has none).
        unlocked_title_name: Optional[str] = None
        if unlock_title_id:
            try:
                cur = await db.execute(
                    "SELECT name FROM title_definitions WHERE id=?",
                    (unlock_title_id,),
                )
                t_row = await cur.fetchone()
                if t_row:
                    cur = await db.execute(
                        "SELECT 1 FROM user_unlocked_titles WHERE guild_id=? AND user_id=? AND title_id=?",
                        (guild_id, user_id, unlock_title_id),
                    )
                    already = await cur.fetchone()
                    if not already:
                        await db.execute(
                            "INSERT OR IGNORE INTO user_unlocked_titles (guild_id, user_id, title_id, unlocked_at) "
                            "VALUES (?, ?, ?, ?)",
                            (guild_id, user_id, unlock_title_id, now_utc().isoformat()),
                        )
                        # Auto-equip only when nothing is currently equipped.
                        cur = await db.execute(
                            "SELECT title FROM user_titles WHERE guild_id=? AND user_id=?",
                            (guild_id, user_id),
                        )
                        eq_row = await cur.fetchone()
                        currently_equipped = eq_row[0] if eq_row else None
                        if not currently_equipped:
                            await db.execute(
                                "INSERT INTO user_titles (guild_id, user_id, title) VALUES (?, ?, ?) "
                                "ON CONFLICT(guild_id, user_id) DO UPDATE SET title=excluded.title",
                                (guild_id, user_id, unlock_title_id),
                            )
                        await db.commit()
                        unlocked_title_name = str(t_row[0])
            except Exception as _e:
                logger.debug(f"[achievement] title auto-unlock failed for {achievement_id}: {_e}")

        notify_style = await get_achievement_notify_style(guild_id, user_id)

        def _achievement_embed(client_obj=None):
            from core.utils import obsidian_embed
            reward_parts = []
            if reward_coins > 0:
                reward_parts.append(f"💰 **{reward_coins:,}** coins")
            if reward_xp > 0:
                reward_parts.append(f"⭐ **{reward_xp:,}** XP")
            reward_line = "  ·  ".join(reward_parts) if reward_parts else None
            fields = []
            if reward_line:
                fields.append(("🎁 Rewards", reward_line, False))
            return obsidian_embed(
                "🏆 Achievement Unlocked!",
                f"> **{ach_name}**\n{ach_description}",
                category="prestige",
                fields=fields if fields else None,
                footer="Use /general achievements to view all your achievements",
                client=client_obj,
            )

        async def _resolve_member():
            member = None
            try:
                guild_obj = bot.get_guild(guild_id) if bot and hasattr(bot, "get_guild") else None
                if guild_obj:
                    member = guild_obj.get_member(user_id)
            except Exception:
                member = None
            if member is None and bot is not None:
                try:
                    member = await bot.fetch_user(user_id)
                except Exception:
                    member = None
            return member

        if notify_style != "off":
            if unlocked_title_name and bot is not None and notify_style in ("dm", "ephemeral"):
                try:
                    member = await _resolve_member()
                    if member is not None:
                        from core.utils import obsidian_embed
                        title_embed = obsidian_embed(
                            "🏅 Title unlocked!",
                            f"You unlocked the **{unlocked_title_name}** title from your latest achievement.",
                            category="prestige",
                            client=bot,
                            footer="Equip with /general profile or /badges title.",
                        )
                        try:
                            await member.send(embed=title_embed)
                        except Exception:
                            pass
                except Exception as _e:
                    logger.debug(f"[achievement] title DM failed: {_e}")

            try:
                ach_embed = _achievement_embed(getattr(interaction, "client", None) if interaction else bot)
                if notify_style == "ephemeral" and interaction is not None:
                    await interaction.followup.send(embed=ach_embed, ephemeral=True)
                elif notify_style == "dm" and bot is not None:
                    member = await _resolve_member()
                    if member is not None:
                        try:
                            await member.send(embed=ach_embed)
                        except Exception:
                            pass
                elif notify_style == "channel" and bot is not None:
                    import discord as _discord
                    guild_obj = bot.get_guild(guild_id) if hasattr(bot, "get_guild") else None
                    if guild_obj:
                        from core.utils import XP_LEVELUP_CHANNEL_KEY
                        ch_id_s = await get_guild_setting(guild_id, XP_LEVELUP_CHANNEL_KEY)
                        ch_id = int(ch_id_s) if ch_id_s and str(ch_id_s).isdigit() else None
                        ch = guild_obj.get_channel(ch_id) if ch_id else guild_obj.system_channel
                        if isinstance(ch, _discord.TextChannel):
                            try:
                                member = guild_obj.get_member(user_id)
                                mention = member.mention if member else f"<@{user_id}>"
                                await ch.send(content=mention, embed=ach_embed)
                            except Exception:
                                pass
            except Exception:
                pass

        return True  # Newly unlocked


async def check_voice_lifetime_achievements(guild_id: int, user_id: int, bot: Optional[Any] = None) -> None:
    """Unlock voice-time achievements (and linked badges) from cumulative ``activity_stats.voice_minutes``."""
    async with open_db() as db:
        cur = await db.execute(
            "SELECT voice_minutes FROM activity_stats WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
    total_mins = int(row[0]) if row and row[0] is not None else 0
    milestones = [
        (60, "voice_hour"),
        (600, "voice_ten_hours"),
        (6000, "voice_100_hours"),
        (60000, "voice_1000_hours"),
    ]
    for need, ach_id in milestones:
        if total_mins >= need:
            try:
                await check_and_unlock_achievement(guild_id, user_id, ach_id, bot)
            except Exception:
                pass


async def initialize_achievement_definitions():
    """Initialize default achievement definitions if they don't exist.

    Item 107: each row may include an ``unlock_title_id`` (8th element)
    that maps to ``title_definitions.id``. When the achievement unlocks,
    the linked title is also unlocked (and auto-equipped if the user has
    no title set yet).
    """
    default_achievements = [
        ("first_message", "First Message", "Send your first message", "social", "Send 1 message", 10, 5, None),
        ("hundred_messages", "Century", "Send 100 messages", "social", "Send 100 messages", 100, 50, None),
        ("thousand_messages", "Millennium", "Send 1,000 messages", "social", "Send 1,000 messages", 500, 250, None),
        ("ten_thousand_messages", "Legend", "Send 10,000 messages", "social", "Send 10,000 messages", 2000, 1000, "chatterbox"),
        ("level_10", "Rising Star", "Reach level 10", "leveling", "Reach level 10", 200, 100, None),
        ("level_25", "Veteran", "Reach level 25", "leveling", "Reach level 25", 500, 250, None),
        ("level_50", "Master", "Reach level 50", "leveling", "Reach level 50", 1000, 500, None),
        ("level_100", "Grandmaster", "Reach level 100", "leveling", "Reach level 100", 5000, 2500, None),
        ("join_anniversary_1", "One Year", "Celebrate 1 year in the server", "milestone", "1 year anniversary", 500, 250, "early_bird"),
        ("join_anniversary_2", "Two Years", "Celebrate 2 years in the server", "milestone", "2 year anniversary", 1000, 500, None),
        ("voice_hour", "Voice Active", "Spend 1 hour in voice", "voice", "1 hour in voice", 50, 25, None),
        ("voice_ten_hours", "Voice Veteran", "Spend 10 hours in voice", "voice", "10 hours in voice", 200, 100, None),
        ("voice_100_hours", "Voice Centurion", "Spend 100 hours in voice", "voice", "100 hours in voice", 1000, 500, None),
        ("voice_1000_hours", "Voice Legend", "Spend 1,000 hours in voice", "voice", "1000 hours in voice", 5000, 2500, None),
        ("pet_first", "Pet Owner", "Get your first pet", "pets", "Own a pet", 50, 25, None),
        ("pet_battle_win", "Pet Fighter", "Win your first pet battle", "pets", "Win 1 pet battle", 75, 50, None),
        ("pet_battle_5", "Pet Champion", "Win 5 pet battles", "pets", "Win 5 pet battles", 200, 100, None),
        ("pet_level_25", "Pet Trainer", "Level your pet to 25", "pets", "Pet reaches level 25", 150, 75, None),
        ("pet_evolved", "Pet Evolver", "Evolve your pet", "pets", "Evolve a pet", 250, 125, None),
        ("daily_streak_10", "Dedicated", "10-day daily streak", "economy", "10 day streak", 200, 100, None),
        ("first_transfer", "Trader", "Complete your first coin transfer", "economy", "Transfer coins once", 25, 10, None),
        ("first_million", "Millionaire", "Reach 1,000,000 coins", "economy", "Balance reaches 1M", 500, 250, "millionaire"),
        ("gambling_first_win", "Lucky", "Win your first gambling game", "economy", "Win slots or dice once", 50, 25, None),
        ("gambling_jackpot", "High Roller", "Hit a slots jackpot (1000 coins)", "economy", "Slots jackpot", 100, 50, None),
        ("event_first", "First Ops", "RSVP to your first event", "milestone", "RSVP GOING to 1 event", 50, 25, None),
        ("event_10", "Regular", "RSVP to 10 events", "milestone", "RSVP to 10 events", 150, 75, None),
        ("event_50", "Veteran Attendee", "RSVP to 50 events", "milestone", "RSVP to 50 events", 500, 250, None),
        ("months_3", "Three Months", "3 months in the server", "milestone", "3 month anniversary", 100, 50, None),
        ("months_6", "Half Year", "6 months in the server", "milestone", "6 month anniversary", 200, 100, "veteran"),
        ("ticket_creator", "Ticket Opener", "Create your first support ticket", "social", "Open 1 ticket", 25, 10, None),
        ("suggestion_first", "Idea Person", "Submit your first suggestion", "social", "Submit 1 suggestion", 25, 10, None),
    ]

    async with open_db() as db:
        for achievement_id, name, description, category, requirement, reward_coins, reward_xp, unlock_title_id in default_achievements:
            await db.execute("""
                INSERT OR IGNORE INTO achievement_definitions
                (achievement_id, name, description, category, requirement, reward_coins, reward_xp, unlock_title_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (achievement_id, name, description, category, requirement, reward_coins, reward_xp, unlock_title_id))
            # Idempotent backfill so existing rows pick up new title links on bot upgrade.
            if unlock_title_id:
                await db.execute(
                    "UPDATE achievement_definitions SET unlock_title_id=? "
                    "WHERE achievement_id=? AND (unlock_title_id IS NULL OR unlock_title_id='')",
                    (unlock_title_id, achievement_id),
                )
        await db.commit()


async def get_all_title_definitions() -> list:
    """Get all title definitions."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT id, name, description, unlock_type, unlock_value, cost_coins
            FROM title_definitions ORDER BY cost_coins ASC, name ASC
        """)
        return await cur.fetchall()


async def get_user_unlocked_titles(guild_id: int, user_id: int) -> set:
    """Get set of title IDs unlocked by user."""
    async with open_db() as db:
        cur = await db.execute("""
            SELECT title_id FROM user_unlocked_titles
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        rows = await cur.fetchall()
        return {r[0] for r in rows}


async def unlock_title_for_user(guild_id: int, user_id: int, title_id: str):
    """Record that user unlocked a title."""
    async with open_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO user_unlocked_titles (guild_id, user_id, title_id, unlocked_at)
            VALUES (?, ?, ?, ?)
        """, (guild_id, user_id, title_id, now_utc().isoformat()))
        await db.commit()


async def check_and_unlock_eligible_titles(guild_id: int, user_id: int) -> list:
    """
    Check if user meets criteria for any locked titles and unlock them.
    Returns list of newly unlocked title IDs.
    """
    from core.config import ECONOMY_ENABLED
    newly_unlocked = []
    definitions = await get_all_title_definitions()
    unlocked = await get_user_unlocked_titles(guild_id, user_id)

    for tid, name, desc, u_type, u_val, cost in definitions:
        if tid in unlocked or u_type == "purchase":
            continue
        try:
            met = False
            if u_type == "balance" and ECONOMY_ENABLED and u_val:
                bal = await get_user_balance(guild_id, user_id)
                met = bal >= int(u_val)
            elif u_type == "months" and u_val:
                months_needed = int(u_val)
                if months_needed <= 6:
                    async with open_db() as db:
                        cur = await db.execute("""
                            SELECT 1 FROM achievements WHERE guild_id=? AND user_id=? AND achievement_id=?
                        """, (guild_id, user_id, f"months_{months_needed}"))
                        met = (await cur.fetchone()) is not None
                else:
                    async with open_db() as db:
                        cur = await db.execute("""
                            SELECT 1 FROM member_milestones
                            WHERE guild_id=? AND user_id=? AND milestone_type='join_anniversary' AND milestone_value>=?
                        """, (guild_id, user_id, months_needed // 12))
                        met = (await cur.fetchone()) is not None
            elif u_type == "messages" and u_val:
                async with open_db() as db:
                    cur = await db.execute("""
                        SELECT messages_sent FROM activity_stats WHERE guild_id=? AND user_id=?
                    """, (guild_id, user_id))
                    row = await cur.fetchone()
                    met = (row and row[0] and row[0] >= int(u_val))
            if met:
                await unlock_title_for_user(guild_id, user_id, tid)
                newly_unlocked.append(tid)
        except Exception as e:
            logger.warning(f"[titles] Error checking title {tid}: {e}")
    return newly_unlocked


async def initialize_title_definitions():
    """Initialize default title definitions (cosmetic titles)."""
    default_titles = [
        # id, name, description, unlock_type, unlock_value, cost_coins
        ("millionaire", "Millionaire", "Reach 1,000,000 coins", "balance", "1000000", 0),
        ("tycoon", "Tycoon", "Reach 10,000,000 coins", "balance", "10000000", 0),
        ("veteran", "Veteran", "Be in the server 6+ months", "months", "6", 0),
        ("early_bird", "Early Bird", "Be in the server 1+ year", "months", "12", 0),
        ("chatterbox", "Chatterbox", "Send 10,000 messages", "messages", "10000", 0),
        ("diamond", "Diamond", "Exclusive cosmetic title", "purchase", None, 50000),
        ("obsidian", "Obsidian", "Premium server title", "purchase", None, 100000),
        ("founder", "Founder", "Support the server", "purchase", None, 250000),
    ]
    async with open_db() as db:
        for tid, name, desc, u_type, u_val, cost in default_titles:
            await db.execute("""
                INSERT OR IGNORE INTO title_definitions (id, name, description, unlock_type, unlock_value, cost_coins)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (tid, name, desc, u_type, u_val or "", cost))
        await db.commit()


async def initialize_badge_definitions():
    """Initialize default badge definitions (achievement-linked badges)."""
    default_badges = [
        ("pet_first", "Pet Owner", "Get your first pet", "🐾", "common"),
        ("pet_battle_win", "Pet Fighter", "Win your first pet battle", "⚔️", "common"),
        ("pet_battle_5", "Pet Champion", "Win 5 pet battles", "🏆", "rare"),
        ("pet_level_25", "Pet Trainer", "Level your pet to 25", "📈", "rare"),
        ("pet_evolved", "Pet Evolver", "Evolve your pet", "✨", "epic"),
        ("daily_streak_10", "Dedicated", "10-day daily streak", "🔥", "rare"),
        ("first_message", "First Message", "Send your first message", "💬", "common"),
        ("level_10", "Rising Star", "Reach level 10", "⭐", "common"),
        ("level_50", "Master", "Reach level 50", "🌟", "epic"),
        ("first_transfer", "Trader", "Complete your first transfer", "💰", "common"),
        ("first_million", "Millionaire", "Reach 1M coins", "💎", "epic"),
        ("gambling_first_win", "Lucky", "Win first gambling game", "🍀", "common"),
        ("gambling_jackpot", "High Roller", "Slots jackpot", "🎰", "rare"),
        ("event_first", "First Ops", "RSVP to first event", "📅", "common"),
        ("event_10", "Regular", "RSVP to 10 events", "🎯", "rare"),
        ("event_50", "Veteran Attendee", "RSVP to 50 events", "🏅", "epic"),
        ("voice_hour", "Voice Active", "1 hour in voice", "🎙️", "common"),
        ("voice_ten_hours", "Voice Veteran", "10 hours in voice", "🎧", "rare"),
        ("voice_100_hours", "Voice Centurion", "100 hours in voice", "📻", "epic"),
        ("voice_1000_hours", "Voice Legend", "1000 hours in voice", "🛰️", "legendary"),
        ("months_3", "Three Months", "3 months in server", "📆", "common"),
        ("months_6", "Half Year", "6 months in server", "⏱️", "rare"),
        ("ticket_creator", "Ticket Opener", "Create first ticket", "🎫", "common"),
        ("suggestion_first", "Idea Person", "Submit first suggestion", "💡", "common"),
    ]
    async with open_db() as db:
        for badge_id, name, description, icon_emoji, rarity in default_badges:
            await db.execute("""
                INSERT OR IGNORE INTO badge_definitions (badge_id, name, description, icon_emoji, rarity)
                VALUES (?, ?, ?, ?, ?)
            """, (badge_id, name, description, icon_emoji, rarity))
        await db.commit()


# --------------------- Shop Functions ---------------------
async def initialize_default_shop_items(guild_id: int):
    """Initialize default shop items for a guild if none exist."""
    async with open_db() as db:
        # Check if shop already has items
        cur = await db.execute("""
            SELECT COUNT(*) FROM shop_items WHERE guild_id=?
        """, (guild_id,))
        count = (await cur.fetchone())[0]
        
        if count > 0:
            return  # Shop already has items
        
        # Default shop items (these are templates - moderators should customize)
        # Note: These don't have actual role IDs - moderators need to add real items
        default_items = [
            # Example items that won't actually work until moderators configure real role IDs
            # These are just placeholders to show the shop is working
        ]
        
        # Don't auto-create items - let moderators add them manually
        # This prevents issues with invalid role IDs


async def _ensure_command_usage_table() -> None:
    async with open_db() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS command_usage (
                guild_id INTEGER NOT NULL,
                command_name TEXT NOT NULL,
                use_count INTEGER NOT NULL DEFAULT 0,
                last_used_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, command_name)
            )
            """
        )
        await db.commit()


async def record_command_usage(
    guild_id: int,
    user_id: int,
    command_name: str,
    weekday: int,
) -> None:
    """Aggregate per-guild command popularity (mods KPI heatmap)."""
    del user_id, weekday
    await _ensure_command_usage_table()
    async with open_db() as db:
        await db.execute(
            """
            INSERT INTO command_usage (guild_id, command_name, use_count, last_used_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(guild_id, command_name) DO UPDATE SET
                use_count = use_count + 1,
                last_used_at = excluded.last_used_at
            """,
            (guild_id, command_name[:120], now_utc().isoformat()),
        )
        await db.commit()


async def track_command_usage(guild_id: int, user_id: int) -> None:
    """Legacy hook — no-op aggregate (per-user tracking not stored)."""
    del guild_id, user_id


async def top_commands(guild_id: int, *, limit: int = 10) -> list[tuple[str, int]]:
    await _ensure_command_usage_table()
    async with open_db() as db:
        cur = await db.execute(
            """
            SELECT command_name, use_count FROM command_usage
            WHERE guild_id=? ORDER BY use_count DESC LIMIT ?
            """,
            (guild_id, limit),
        )
        return list(await cur.fetchall())


# ---------------------------------------------------------------------------
# Database schema (DDL / migrations) lives in database/schema.py
# ---------------------------------------------------------------------------
from database.schema import init_db  # noqa: F401
