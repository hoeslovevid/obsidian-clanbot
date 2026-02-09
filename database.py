"""
Database functions for economy, XP, and guild settings.
This module handles all database operations to keep bot.py clean.
"""
import os
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
from config import DB_PATH

logger = logging.getLogger(__name__)


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


# --------------------- Guild Settings ---------------------
async def get_guild_setting(guild_id: int, key: str) -> Optional[str]:
    """Get a guild setting value."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def set_guild_setting(guild_id: int, key: str, value: str):
    """Set a guild setting value."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)",
            (guild_id, key, value),
        )
        await db.commit()


# --------------------- Economy Functions ---------------------
async def get_user_balance(guild_id: int, user_id: int) -> int:
    """Get a user's coin balance."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def add_coins(guild_id: int, user_id: int, amount: int, transaction_type: str, description: Optional[str] = None) -> None:
    """Add coins to a user's balance."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    
    async with aiosqlite.connect(DB_PATH) as db:
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
    from utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT
    async with aiosqlite.connect(DB_PATH) as db:
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
    """Add XP to a user. Returns True if user leveled up."""
    from utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT
    async with aiosqlite.connect(DB_PATH) as db:
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
    from utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT
    if amount <= 0:
        return False
    
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
            from channels import resolve_channel_id
            from utils import obsidian_embed
            
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
        
        await db.commit()


async def update_activity_voice_minutes(guild_id: int, user_id: int, minutes: int):
    """Update voice minutes in activity stats."""
    async with aiosqlite.connect(DB_PATH) as db:
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


async def reset_weekly_scores():
    """Reset weekly scores (should be called weekly)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE activity_stats SET weekly_score = 0")
        await db.commit()


async def reset_monthly_scores():
    """Reset monthly scores (should be called monthly)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE activity_stats SET monthly_score = 0")
        await db.commit()


# --------------------- Auto-Moderation Functions ---------------------
async def get_auto_mod_settings(guild_id: int) -> Optional[dict]:
    """Get auto-moderation settings for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO auto_mod_violations (guild_id, user_id, violation_type, message_content, action_taken, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, user_id, violation_type, message_content[:500], action_taken, now_utc().isoformat()))
        await db.commit()


async def get_spam_tracking(guild_id: int, user_id: int) -> Optional[dict]:
    """Get spam tracking data for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM auto_mod_spam_tracking WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        await db.commit()


# --------------------- Self-Assignable Roles Functions ---------------------
async def add_self_assignable_role(guild_id: int, role_id: int, category: Optional[str] = None, description: Optional[str] = None, max_roles: Optional[int] = None):
    """Add a self-assignable role."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM self_assignable_roles WHERE guild_id = ? AND role_id = ?
        """, (guild_id, role_id))
        await db.commit()


async def get_self_assignable_roles(guild_id: int, category: Optional[str] = None) -> list:
    """Get all self-assignable roles for a guild, optionally filtered by category."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT DISTINCT category FROM self_assignable_roles
            WHERE guild_id = ? AND category IS NOT NULL
            ORDER BY category
        """, (guild_id,))
        rows = await cur.fetchall()
        return [row[0] for row in rows if row[0]]


# --------------------- Level Roles Functions ---------------------
async def add_level_role(guild_id: int, level: int, role_id: int):
    """Add a level role (role assigned at a specific level)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO level_roles (guild_id, level, role_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id
        """, (guild_id, level, role_id, now_utc().isoformat()))
        await db.commit()


async def remove_level_role(guild_id: int, level: int):
    """Remove a level role."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM level_roles WHERE guild_id = ? AND level = ?
        """, (guild_id, level))
        await db.commit()


async def get_level_roles(guild_id: int) -> list:
    """Get all level roles for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT level, role_id FROM level_roles
            WHERE guild_id = ?
            ORDER BY level ASC
        """, (guild_id,))
        rows = await cur.fetchall()
        return [{"level": row[0], "role_id": row[1]} for row in rows]


async def get_level_role_for_level(guild_id: int, level: int) -> Optional[int]:
    """Get the role ID for a specific level."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT role_id FROM level_roles
            WHERE guild_id = ? AND level = ?
        """, (guild_id, level))
        row = await cur.fetchone()
        return row[0] if row else None


async def get_all_level_roles_up_to(guild_id: int, level: int) -> list:
    """Get all level roles up to and including a specific level."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO linked_steam_accounts (guild_id, user_id, steam_id_64, warframe_ign, linked_at)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, steam_id_64, warframe_ign, now_utc().isoformat()))
        await db.commit()


async def unlink_steam_account(guild_id: int, user_id: int):
    """Unlink a user's Steam account."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM linked_steam_accounts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.commit()


async def get_linked_steam_id(guild_id: int, user_id: int) -> Optional[str]:
    """Get linked Steam 64 ID for a user, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT steam_id_64 FROM linked_steam_accounts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def get_all_linked_steam_accounts(guild_id: int) -> list:
    """Get all (user_id, steam_id_64) for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, steam_id_64 FROM linked_steam_accounts WHERE guild_id=?",
            (guild_id,),
        )
        return await cur.fetchall()


async def update_steam_playtime(guild_id: int, user_id: int, hours: int):
    """Update stored playtime and last checked time."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE linked_steam_accounts
            SET last_playtime_hours=?, last_checked_at=?
            WHERE guild_id=? AND user_id=?
        """, (hours, now_utc().isoformat(), guild_id, user_id))
        await db.commit()


async def add_warframe_achievement_role(guild_id: int, achievement_type: str, threshold_value: int, role_id: int):
    """Add a role to assign when user reaches a playtime threshold."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO warframe_achievement_roles (guild_id, achievement_type, threshold_value, role_id)
            VALUES (?, ?, ?, ?)
        """, (guild_id, achievement_type, threshold_value, role_id))
        await db.commit()


async def remove_warframe_achievement_role(guild_id: int, achievement_type: str, threshold_value: int):
    """Remove a warframe achievement role."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM warframe_achievement_roles
            WHERE guild_id=? AND achievement_type=? AND threshold_value=?
        """, (guild_id, achievement_type, threshold_value))
        await db.commit()


async def get_warframe_achievement_roles(guild_id: int) -> list:
    """Get all warframe achievement role configs: (achievement_type, threshold_value, role_id)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT achievement_type, threshold_value, role_id
            FROM warframe_achievement_roles WHERE guild_id=?
            ORDER BY achievement_type, threshold_value
        """, (guild_id,))
        return await cur.fetchall()


async def record_warframe_achievement_unlock(guild_id: int, user_id: int, achievement_type: str, threshold_value: int):
    """Record that a user has been assigned a role for this achievement."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO warframe_achievement_unlocks
            (guild_id, user_id, achievement_type, threshold_value, unlocked_at)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, achievement_type, threshold_value, now_utc().isoformat()))
        await db.commit()


async def has_warframe_achievement_unlock(guild_id: int, user_id: int, achievement_type: str, threshold_value: int) -> bool:
    """Check if user has already received this achievement role."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT 1 FROM warframe_achievement_unlocks
            WHERE guild_id=? AND user_id=? AND achievement_type=? AND threshold_value=?
        """, (guild_id, user_id, achievement_type, threshold_value))
        return await cur.fetchone() is not None


# --------------------- AFK Functions ---------------------
async def set_afk(guild_id: int, user_id: int, reason: Optional[str] = None):
    """Set a user as AFK."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM afk_users WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        await db.commit()


async def get_afk_status(guild_id: int, user_id: int) -> Optional[dict]:
    """Get a user's AFK status."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE server_stats_channels SET enabled = 0 WHERE guild_id = ?
        """, (guild_id,))
        await db.commit()


async def get_server_stats_channel(guild_id: int) -> Optional[dict]:
    """Get the server stats channel settings."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if already recorded
        cur = await db.execute("""
            SELECT 1 FROM member_milestones
            WHERE guild_id=? AND user_id=? AND milestone_type=? AND milestone_value=?
        """, (guild_id, user_id, milestone_type, milestone_value))
        if await cur.fetchone():
            return False  # Already recorded
        
        # Record milestone
        await db.execute("""
            INSERT INTO member_milestones (guild_id, user_id, milestone_type, milestone_value, achieved_at, notified)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (guild_id, user_id, milestone_type, milestone_value, now_utc().isoformat()))
        await db.commit()
        return True  # Newly achieved


# --------------------- Achievement Functions ---------------------
async def check_and_unlock_achievement(guild_id: int, user_id: int, achievement_id: str, bot: Optional[Any] = None) -> bool:
    """Check if achievement should be unlocked and unlock it. Returns True if achievement was newly unlocked."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if already unlocked
        cur = await db.execute("""
            SELECT 1 FROM achievements
            WHERE guild_id=? AND user_id=? AND achievement_id=?
        """, (guild_id, user_id, achievement_id))
        if await cur.fetchone():
            return False  # Already unlocked
        
        # Get achievement definition
        cur = await db.execute("""
            SELECT reward_coins, reward_xp FROM achievement_definitions
            WHERE achievement_id=?
        """, (achievement_id,))
        row = await cur.fetchone()
        
        reward_coins = row[0] if row else 0
        reward_xp = row[1] if row else 0
        
        # Unlock achievement
        await db.execute("""
            INSERT INTO achievements (guild_id, user_id, achievement_id, unlocked_at)
            VALUES (?, ?, ?, ?)
        """, (guild_id, user_id, achievement_id, now_utc().isoformat()))
        await db.commit()
        
        # Award rewards
        if reward_coins > 0:
            await add_coins(guild_id, user_id, reward_coins, "ACHIEVEMENT", f"Achievement: {achievement_id}")
        if reward_xp > 0:
            await add_xp(guild_id, user_id, reward_xp, f"ACHIEVEMENT_{achievement_id}")
        
        return True  # Newly unlocked


async def initialize_achievement_definitions():
    """Initialize default achievement definitions if they don't exist."""
    default_achievements = [
        ("first_message", "First Message", "Send your first message", "social", "Send 1 message", 10, 5),
        ("hundred_messages", "Century", "Send 100 messages", "social", "Send 100 messages", 100, 50),
        ("thousand_messages", "Millennium", "Send 1,000 messages", "social", "Send 1,000 messages", 500, 250),
        ("ten_thousand_messages", "Legend", "Send 10,000 messages", "social", "Send 10,000 messages", 2000, 1000),
        ("level_10", "Rising Star", "Reach level 10", "leveling", "Reach level 10", 200, 100),
        ("level_25", "Veteran", "Reach level 25", "leveling", "Reach level 25", 500, 250),
        ("level_50", "Master", "Reach level 50", "leveling", "Reach level 50", 1000, 500),
        ("level_100", "Grandmaster", "Reach level 100", "leveling", "Reach level 100", 5000, 2500),
        ("join_anniversary_1", "One Year", "Celebrate 1 year in the server", "milestone", "1 year anniversary", 500, 250),
        ("join_anniversary_2", "Two Years", "Celebrate 2 years in the server", "milestone", "2 year anniversary", 1000, 500),
        ("voice_hour", "Voice Active", "Spend 1 hour in voice", "voice", "1 hour in voice", 50, 25),
        ("voice_ten_hours", "Voice Veteran", "Spend 10 hours in voice", "voice", "10 hours in voice", 200, 100),
    ]
    
    async with aiosqlite.connect(DB_PATH) as db:
        for achievement_id, name, description, category, requirement, reward_coins, reward_xp in default_achievements:
            await db.execute("""
                INSERT OR IGNORE INTO achievement_definitions 
                (achievement_id, name, description, category, requirement, reward_coins, reward_xp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (achievement_id, name, description, category, requirement, reward_coins, reward_xp))
        await db.commit()


# --------------------- Shop Functions ---------------------
async def initialize_default_shop_items(guild_id: int):
    """Initialize default shop items for a guild if none exist."""
    async with aiosqlite.connect(DB_PATH) as db:
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


# --------------------- Database Initialization ---------------------
async def init_db() -> None:
    """Initialize all database tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (guild_id, key)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS temp_vcs (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            last_nonempty_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS vc_panels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT NOT NULL,
            details TEXT NOT NULL,
            evidence TEXT,
            status TEXT NOT NULL,
            staff_thread_id INTEGER,
            last_update_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, case_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaint_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            actor_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS events (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            start_ts INTEGER NOT NULL,
            end_ts INTEGER,
            description TEXT NOT NULL,
            role_id INTEGER,
            created_at TEXT NOT NULL,
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            ended INTEGER NOT NULL DEFAULT 0,
            recap_posted INTEGER NOT NULL DEFAULT 0,
            recap_message_id INTEGER,
            thread_id INTEGER,
            PRIMARY KEY (guild_id, message_id)
        )""")

        # Event automation (columns on existing table)
        try:
            cur = await db.execute("PRAGMA table_info(events)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]

            if "end_ts" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN end_ts INTEGER")
            if "ended" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN ended INTEGER NOT NULL DEFAULT 0")
            if "recap_posted" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN recap_posted INTEGER NOT NULL DEFAULT 0")
            if "recap_message_id" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN recap_message_id INTEGER")

            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding event automation columns: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS event_rsvps (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            PRIMARY KEY (guild_id, message_id, user_id)
        )""")

        # Economy tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_balances (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            total_earned INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS economy_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS voice_activity (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            last_reward_at TEXT,
            total_minutes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS message_cooldowns (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_message_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_xp (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            total_xp INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS daily_claims (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_claim_date TEXT NOT NULL,
            streak_days INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arrival_time TEXT NOT NULL,
            departure_time TEXT NOT NULL,
            location TEXT NOT NULL,
            inventory_json TEXT,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_live_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            expiry_time TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, channel_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS lfg_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            mission_type TEXT NOT NULL,
            player_count INTEGER NOT NULL,
            max_players INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            thread_id INTEGER
        )""")

        # LFG enhancements (optional ping role + close metadata)
        try:
            cur = await db.execute("PRAGMA table_info(lfg_posts)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]

            if "ping_role_id" not in column_names:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN ping_role_id INTEGER")
            if "closed_at" not in column_names:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN closed_at TEXT")
            if "closed_by" not in column_names:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN closed_by INTEGER")

            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding LFG enhancement columns: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS lfg_rsvps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lfg_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (lfg_id) REFERENCES lfg_posts(id) ON DELETE CASCADE,
            UNIQUE(lfg_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cycle_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            cetus_enabled INTEGER NOT NULL DEFAULT 0,
            fortuna_enabled INTEGER NOT NULL DEFAULT 0,
            deimos_enabled INTEGER NOT NULL DEFAULT 0,
            ping_role_id INTEGER,
            PRIMARY KEY (guild_id)
        )""")
        # Migration: add ping_role_id if missing (existing DBs)
        try:
            cur = await db.execute("PRAGMA table_info(cycle_notification_settings)")
            cols = [row[1] for row in await cur.fetchall()]
            if "ping_role_id" not in cols:
                await db.execute("ALTER TABLE cycle_notification_settings ADD COLUMN ping_role_id INTEGER")
                await db.commit()
        except Exception as e:
            logger.warning(f"[db] cycle_notification_settings ping_role_id migration: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cycle_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            cycle_type TEXT NOT NULL,
            cycle_state TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, cycle_type, cycle_state, notified_at)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS invasion_notification_settings (
            guild_id INTEGER NOT NULL,
            reward_lower TEXT NOT NULL,
            reward_display TEXT NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, reward_lower)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS invasion_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            invasion_id TEXT NOT NULL,
            reward_lower TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, invasion_id, reward_lower)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS archon_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS archon_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            archon_boss TEXT NOT NULL,
            expiry_time TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, archon_boss, expiry_time)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS member_count_channels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            channel_type TEXT NOT NULL DEFAULT 'voice',
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_event_settings (
            guild_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_discord_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            warframe_event_id TEXT NOT NULL,
            discord_event_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, warframe_event_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            suggestion_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            message_id INTEGER,
            created_at TEXT NOT NULL,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            review_note TEXT
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            panel_channel_id INTEGER,
            panel_message_id INTEGER,
            panel_description TEXT,
            panel_image_url TEXT
        )""")
        
        # Add panel columns if they don't exist (for existing databases)
        try:
            cur = await db.execute("PRAGMA table_info(application_settings)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]
            
            if "panel_channel_id" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_channel_id INTEGER")
                logger.info("[db] Added panel_channel_id column to application_settings table")
            
            if "panel_message_id" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_message_id INTEGER")
                logger.info("[db] Added panel_message_id column to application_settings table")
            
            if "panel_description" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_description TEXT")
                logger.info("[db] Added panel_description column to application_settings table")
            
            if "panel_image_url" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_image_url TEXT")
                logger.info("[db] Added panel_image_url column to application_settings table")
            
            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding panel columns: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            question_order INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            UNIQUE(guild_id, question_order)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
            current_question_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            submitted_at TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            review_note TEXT,
            message_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            response_text TEXT NOT NULL,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES application_questions(id) ON DELETE CASCADE
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS update_log_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS update_log_posted_versions (
            guild_id INTEGER NOT NULL,
            version TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, version)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_version_tracking (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_version TEXT NOT NULL,
            feature_hash TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            previous_commands TEXT
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reaction_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id, emoji)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS welcome_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            message TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS leave_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            message TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            prize TEXT NOT NULL,
            winner_count INTEGER NOT NULL DEFAULT 1,
            end_time TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            ended INTEGER NOT NULL DEFAULT 0,
            ended_at TEXT,
            required_role_id INTEGER,
            min_level INTEGER,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            entered_at TEXT NOT NULL,
            UNIQUE(giveaway_id, user_id),
            FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            spam_enabled INTEGER NOT NULL DEFAULT 1,
            spam_threshold INTEGER NOT NULL DEFAULT 5,
            spam_interval INTEGER NOT NULL DEFAULT 10,
            caps_enabled INTEGER NOT NULL DEFAULT 1,
            caps_threshold INTEGER NOT NULL DEFAULT 70,
            caps_min_length INTEGER NOT NULL DEFAULT 10,
            links_enabled INTEGER NOT NULL DEFAULT 0,
            links_whitelist TEXT,
            mention_enabled INTEGER NOT NULL DEFAULT 1,
            mention_limit INTEGER NOT NULL DEFAULT 5,
            punishment_action TEXT NOT NULL DEFAULT 'delete',
            punishment_duration INTEGER,
            log_channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            violation_type TEXT NOT NULL,
            message_content TEXT,
            action_taken TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_spam_tracking (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 1,
            first_message_time TEXT NOT NULL,
            last_message_time TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS self_assignable_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            category TEXT,
            description TEXT,
            max_roles INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, role_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS level_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, level)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS afk_users (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT,
            set_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_stats_channels (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            stats_type TEXT NOT NULL DEFAULT 'members',
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS alert_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            alert_id TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, alert_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS devstream_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            devstream_date TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, devstream_date, notification_type)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            interest_rate REAL NOT NULL DEFAULT 0.05,
            invested_at TEXT NOT NULL,
            maturity_date TEXT NOT NULL,
            collected INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, invested_at)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS log_channels (
            guild_id INTEGER NOT NULL,
            log_type TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, log_type)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS deleted_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT,
            author_name TEXT,
            author_avatar TEXT,
            attachments TEXT,
            embeds TEXT,
            deleted_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS edited_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            old_content TEXT,
            new_content TEXT,
            author_name TEXT,
            edited_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS member_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            milestone_type TEXT NOT NULL,
            milestone_value INTEGER NOT NULL,
            achieved_at TEXT NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, milestone_type, milestone_value)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            UNIQUE(guild_id, user_id, achievement_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS achievement_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            achievement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            requirement TEXT,
            reward_coins INTEGER DEFAULT 0,
            reward_xp INTEGER DEFAULT 0,
            UNIQUE(achievement_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS music_queues (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            voice_channel_id INTEGER NOT NULL,
            current_track TEXT,
            queue_json TEXT,
            is_playing INTEGER NOT NULL DEFAULT 0,
            volume INTEGER NOT NULL DEFAULT 50,
            updated_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS webhook_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            endpoint_name TEXT NOT NULL,
            webhook_url TEXT NOT NULL,
            event_types TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, endpoint_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            description TEXT NOT NULL,
            price INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_value TEXT,
            stock INTEGER DEFAULT -1,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, item_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            price_paid INTEGER NOT NULL,
            purchased_at TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES shop_items(id)
        )""")
        
        # Add previous_commands column if it doesn't exist (for existing databases)
        # Check if column exists first to avoid errors
        try:
            cur = await db.execute("PRAGMA table_info(bot_version_tracking)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]
            if "previous_commands" not in column_names:
                await db.execute("ALTER TABLE bot_version_tracking ADD COLUMN previous_commands TEXT")
                await db.commit()
                logger.info("[db] Added previous_commands column to bot_version_tracking table")
        except Exception as e:
            logger.warning(f"[db] Error checking/adding previous_commands column: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trading_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            listing_type TEXT NOT NULL,
            item_name TEXT NOT NULL,
            price INTEGER,
            quantity INTEGER DEFAULT 1,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            message_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            platform TEXT NOT NULL DEFAULT 'pc'
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trading_channel_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS activity_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            commands_used INTEGER NOT NULL DEFAULT 0,
            events_attended INTEGER NOT NULL DEFAULT 0,
            voice_minutes INTEGER NOT NULL DEFAULT 0,
            messages_sent INTEGER NOT NULL DEFAULT 0,
            last_activity_date TEXT NOT NULL,
            weekly_score INTEGER NOT NULL DEFAULT 0,
            monthly_score INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL,
            activity_date TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0
        )""")

        # Ticket system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            ticket_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            closed_at TEXT,
            closed_by INTEGER,
            UNIQUE(guild_id, ticket_id)
        )""")

        # Ticket enhancements (columns on existing table)
        # - assigned_to: who claimed/owns the ticket (mod id)
        # - claimed_at: when it was claimed
        # - first_response_at: first staff response time
        # - last_activity_at: last message time (user or staff)
        # - sla_minutes: per-ticket SLA target (minutes)
        # - control_message_id: message id of the ticket control panel in the ticket channel
        # - satisfaction_rating/feedback: post-close feedback
        # - transcript_channel_id/transcript_message_id: where transcript was posted
        try:
            cur = await db.execute("PRAGMA table_info(tickets)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]

            if "assigned_to" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN assigned_to INTEGER")
            if "claimed_at" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN claimed_at TEXT")
            if "first_response_at" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN first_response_at TEXT")
            if "last_activity_at" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN last_activity_at TEXT")
            if "sla_minutes" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN sla_minutes INTEGER DEFAULT 60")
            if "control_message_id" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN control_message_id INTEGER")
            if "satisfaction_rating" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN satisfaction_rating INTEGER")
            if "satisfaction_feedback" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN satisfaction_feedback TEXT")
            if "transcript_channel_id" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN transcript_channel_id INTEGER")
            if "transcript_message_id" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN transcript_message_id INTEGER")

            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding ticket enhancement columns: {e}")

        # Ticket notes (internal staff notes)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ticket_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            ticket_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
        )""")

        # Ticket canned responses (quick replies)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ticket_canned_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, name)
        )""")

        # Gambling tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS gambling_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            game_type TEXT NOT NULL,
            bet_amount INTEGER NOT NULL,
            win_amount INTEGER NOT NULL,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        # Server rules tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            rule_number INTEGER NOT NULL,
            rule_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, rule_number)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            accepted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS rules_channel_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            message_id INTEGER
        )""")

        # Poll system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            ends_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS poll_votes (
            poll_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            option_index INTEGER NOT NULL,
            voted_at TEXT NOT NULL,
            PRIMARY KEY (poll_id, user_id),
            FOREIGN KEY (poll_id) REFERENCES polls(id)
        )""")

        # Warn system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warn_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            max_warnings INTEGER NOT NULL DEFAULT 3,
            action_after_max TEXT NOT NULL DEFAULT 'mute',
            mute_duration INTEGER,
            log_channel_id INTEGER
        )""")

        # Reminder system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER,
            reminder_text TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0
        )""")

        # Starboard tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS starboard_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            threshold INTEGER NOT NULL DEFAULT 5,
            emoji TEXT NOT NULL DEFAULT '⭐'
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS starboard_messages (
            guild_id INTEGER NOT NULL,
            original_message_id INTEGER NOT NULL,
            starboard_message_id INTEGER NOT NULL,
            stars INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, original_message_id)
        )""")

        # Reputation system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reputation (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reputation_points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reputation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            giver_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )""")

        # Twitch integration tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS twitch_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 0,
            ping_role_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS twitch_streamers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            streamer_name TEXT NOT NULL,
            twitch_user_id TEXT,
            last_live_status INTEGER NOT NULL DEFAULT 0,
            last_notified_at TEXT,
            UNIQUE(guild_id, streamer_name)
        )""")

        # Role menu tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS role_menus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            max_roles INTEGER,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS role_menu_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            emoji TEXT,
            description TEXT,
            FOREIGN KEY (menu_id) REFERENCES role_menus(id) ON DELETE CASCADE
        )""")

        # Clan Dojo tracker tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS dojo_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            research_name TEXT NOT NULL,
            research_type TEXT NOT NULL,
            required_resources TEXT,
            current_resources TEXT,
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(guild_id, research_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS dojo_decorations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            decoration_name TEXT NOT NULL,
            room_location TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            added_at TEXT NOT NULL
        )""")

        # Pet system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pet_name TEXT NOT NULL,
            pet_type TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            experience INTEGER NOT NULL DEFAULT 0,
            hunger INTEGER NOT NULL DEFAULT 100,
            happiness INTEGER NOT NULL DEFAULT 100,
            last_fed_at TEXT,
            last_played_at TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_type TEXT NOT NULL UNIQUE,
            base_price INTEGER NOT NULL,
            max_level INTEGER NOT NULL DEFAULT 100,
            description TEXT
        )""")
        # Seed default pets if shop is empty
        cur = await db.execute("SELECT COUNT(*) FROM pet_types")
        if (await cur.fetchone())[0] == 0:
            default_pets = [
                ("Dog", 100, 50, "A loyal companion"),
                ("Cat", 150, 60, "An independent friend"),
                ("Bird", 80, 40, "A cheerful winged friend"),
                ("Fish", 75, 35, "A calm aquarium buddy"),
                ("Rabbit", 120, 55, "A soft and speedy pal"),
                ("Fox", 200, 70, "A clever and curious companion"),
                ("Robot", 300, 80, "A mechanical companion"),
                ("Wolf", 350, 85, "A fierce and loyal guardian"),
                ("Dragon", 500, 100, "A powerful mythical creature"),
                ("Phoenix", 600, 100, "A legendary fire bird that rises again"),
            ]
            for pet_type, base_price, max_level, description in default_pets:
                await db.execute(
                    "INSERT OR IGNORE INTO pet_types (pet_type, base_price, max_level, description) VALUES (?, ?, ?, ?)",
                    (pet_type, base_price, max_level, description),
                )
            await db.commit()

        # Prestige system tables
        # Warframe in-game achievement roles (Steam playtime, etc.)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS linked_steam_accounts (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            steam_id_64 TEXT NOT NULL,
            warframe_ign TEXT,
            linked_at TEXT NOT NULL,
            last_playtime_hours INTEGER,
            last_checked_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")
        # Migration: add warframe_ign if missing
        try:
            cur = await db.execute("PRAGMA table_info(linked_steam_accounts)")
            cols = [row[1] for row in await cur.fetchall()]
            if "warframe_ign" not in cols:
                await db.execute("ALTER TABLE linked_steam_accounts ADD COLUMN warframe_ign TEXT")
                await db.commit()
        except Exception:
            pass
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_achievement_roles (
            guild_id INTEGER NOT NULL,
            achievement_type TEXT NOT NULL,
            threshold_value INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, achievement_type, threshold_value)
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_achievement_unlocks (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            achievement_type TEXT NOT NULL,
            threshold_value INTEGER NOT NULL,
            unlocked_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id, achievement_type, threshold_value)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_prestige (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            prestige_level INTEGER NOT NULL DEFAULT 0,
            total_prestige_xp INTEGER NOT NULL DEFAULT 0,
            last_prestige_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Badge/Title system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            badge_id TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            is_equipped INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, badge_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS badge_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            badge_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            icon_emoji TEXT,
            rarity TEXT NOT NULL DEFAULT 'common',
            requirement TEXT,
            reward_coins INTEGER DEFAULT 0,
            reward_xp INTEGER DEFAULT 0
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_titles (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            title TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Scheduled announcements tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            embed_json TEXT,
            schedule_type TEXT NOT NULL,
            schedule_value TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")

        # Server milestones tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            milestone_type TEXT NOT NULL,
            milestone_value INTEGER NOT NULL,
            achieved_at TEXT NOT NULL,
            announced INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, milestone_type, milestone_value)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_milestone_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            member_count_enabled INTEGER NOT NULL DEFAULT 1,
            anniversary_enabled INTEGER NOT NULL DEFAULT 1,
            announcement_channel_id INTEGER
        )""")

        # Raid protection tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS raid_protection_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            join_threshold INTEGER NOT NULL DEFAULT 10,
            time_window_seconds INTEGER NOT NULL DEFAULT 60,
            action TEXT NOT NULL DEFAULT 'lockdown',
            lockdown_duration_minutes INTEGER NOT NULL DEFAULT 30,
            alert_channel_id INTEGER,
            alert_role_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS recent_joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            account_age_days INTEGER,
            joined_at TEXT NOT NULL
        )""")

        # Cross-server communication tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_alliances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            allied_guild_id INTEGER NOT NULL,
            alliance_name TEXT,
            created_at TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            UNIQUE(guild_id, allied_guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cross_server_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_guild_id INTEGER NOT NULL,
            to_guild_id INTEGER NOT NULL,
            from_user_id INTEGER NOT NULL,
            message_content TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            read INTEGER NOT NULL DEFAULT 0
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cross_server_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            alliance_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (alliance_id) REFERENCES server_alliances(id) ON DELETE CASCADE
        )""")

        # Voice activity leaderboard tables (enhancement)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS voice_leaderboard_cache (
            guild_id INTEGER NOT NULL,
            period_type TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            voice_minutes INTEGER NOT NULL DEFAULT 0,
            rank INTEGER,
            last_updated TEXT NOT NULL,
            PRIMARY KEY (guild_id, period_type, user_id)
        )""")

        # Create indexes for common queries to improve performance
        logger.info("[db] Creating indexes for performance optimization...")
        
        # Indexes for frequently queried columns
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_balances_guild_user ON user_balances(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_xp_guild_user ON user_xp(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_activity_stats_guild_user ON activity_stats(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_transactions_guild_user ON economy_transactions(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_transactions_created ON economy_transactions(created_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_voice_activity_guild_user ON voice_activity(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_recent_joins_guild_time ON recent_joins(guild_id, joined_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_next_run ON scheduled_announcements(next_run_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_polls_guild_message ON polls(guild_id, message_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_applications_guild_status ON applications(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_complaints_guild_status ON complaints(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_giveaways_ended ON giveaways(ended)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trading_posts_guild_status ON trading_posts(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_log_channels_guild_type ON log_channels(guild_id, log_type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_auto_mod_settings_guild ON auto_mod_settings(guild_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_auto_mod_spam_tracking_guild_user ON auto_mod_spam_tracking(guild_id, user_id)")

            # Tickets
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_channel_status ON tickets(channel_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_guild_user ON tickets(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ticket_notes_ticket ON ticket_notes(ticket_id)")

            # Events
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_guild_start ON events(guild_id, start_ts)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_guild_end ON events(guild_id, end_ts)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_rsvps_message ON event_rsvps(guild_id, message_id)")

            # LFG
            await db.execute("CREATE INDEX IF NOT EXISTS idx_lfg_posts_status_expires ON lfg_posts(status, expires_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_lfg_rsvps_lfg ON lfg_rsvps(lfg_id)")
            
            await db.commit()
            logger.info("[db] Indexes created successfully")
        except Exception as e:
            logger.warning(f"[db] Error creating indexes (may already exist): {e}")
        
        await db.commit()
        logger.info("[db] Database tables initialized successfully")
