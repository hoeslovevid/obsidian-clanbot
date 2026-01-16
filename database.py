"""
Database functions for economy, XP, and guild settings.
This module handles all database operations to keep bot.py clean.
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import aiosqlite  # type: ignore

# Import DB_PATH from environment
DB_PATH = os.getenv("DB_PATH", "obsidian_clanbot.db")


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


async def add_coins(guild_id: int, user_id: int, amount: int, transaction_type: str, description: Optional[str] = None):
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
def calculate_level(xp: int, multiplier: int = 100) -> int:
    """Calculate level from XP. Formula: XP = level^2 * multiplier"""
    if xp <= 0:
        return 0
    import math
    level = int(math.sqrt(xp / multiplier))
    return max(0, level)


def xp_for_level(level: int, multiplier: int = 100) -> int:
    """Calculate XP needed for a specific level."""
    return int(level ** 2 * multiplier)


def xp_for_next_level(current_level: int, multiplier: int = 100) -> int:
    """Calculate XP needed to reach the next level."""
    return xp_for_level(current_level + 1, multiplier)


async def get_user_xp(guild_id: int, user_id: int) -> Tuple[int, int, int]:
    """Get a user's XP, level, and total XP. Returns (xp, level, total_xp)."""
    from utils import XP_LEVEL_MULTIPLIER
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT xp, level, total_xp FROM user_xp WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        if row:
            xp, level, total_xp = row
            # Recalculate level in case XP changed
            actual_level = calculate_level(xp, XP_LEVEL_MULTIPLIER)
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
    from utils import XP_LEVEL_MULTIPLIER
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
        new_level = calculate_level(new_xp, XP_LEVEL_MULTIPLIER)
        
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
    from utils import XP_LEVEL_MULTIPLIER
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
        new_level = calculate_level(new_xp, XP_LEVEL_MULTIPLIER)
        
        # Update
        await db.execute("""
            UPDATE user_xp
            SET xp = ?, level = ?
            WHERE guild_id=? AND user_id=?
        """, (new_xp, new_level, guild_id, user_id))
        
        await db.commit()
        return True


# --------------------- Complaint Functions ---------------------
async def log_complaint_action(guild_id: int, case_id: str, actor_id: int, action: str, note: str = ""):
    """Log a complaint action."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO complaint_actions (guild_id, case_id, actor_id, action, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, case_id, actor_id, action, note, now_utc().isoformat()))
        await db.commit()


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
