"""
Database functions for economy, XP, and guild settings.
This module handles all database operations to keep bot.py clean.
"""
import os
from datetime import datetime, timezone
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


async def add_xp(guild_id: int, user_id: int, amount: int, source: str = "ACTIVITY"):
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
