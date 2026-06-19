"""Bot process entrypoint (extracted from bot/app.py)."""
from __future__ import annotations

import logging
import os

import discord  # type: ignore

from core.db import open_db
from database import init_db

logger = logging.getLogger(__name__)


async def run_bot(bot) -> None:
    from core.config import DB_PATH, TOKEN

    await init_db()

    db_dir = os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else "."
    db_filename = os.path.basename(DB_PATH)

    logger.info(f"[startup] Database path: {DB_PATH}")
    logger.info(f"[startup] Database directory: {os.path.abspath(db_dir)}")
    logger.info(f"[startup] Database filename: {db_filename}")

    if os.path.exists(DB_PATH):
        db_size = os.path.getsize(DB_PATH)
        logger.info(f"[startup] Database file found: {DB_PATH} ({db_size} bytes)")
        if os.access(db_dir, os.W_OK):
            logger.info(f"[startup] Database directory is writable: {db_dir}")
        else:
            logger.warning(f"[startup] Database directory may not be writable: {db_dir}")
    else:
        logger.warning(f"[startup] Database file not found: {DB_PATH} (will be created)")
        if not os.path.exists(db_dir):
            logger.warning(f"[startup] Database directory does not exist: {db_dir} (will be created)")
        elif not os.access(db_dir, os.W_OK):
            logger.error(f"[startup] Database directory is not writable: {db_dir}")
        else:
            logger.info(f"[startup] Database directory is writable: {db_dir}")

    async with open_db() as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='update_log_settings'"
        )
        if not await cur.fetchone():
            logger.error("[startup] CRITICAL: update_log_settings table not found!")
        else:
            logger.info("[startup] Update log settings table verified")

        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_version_tracking'"
        )
        if not await cur.fetchone():
            logger.error("[startup] CRITICAL: bot_version_tracking table not found!")
        else:
            logger.info("[startup] Bot version tracking table verified")

    try:
        await bot.start(TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print("\n" + "=" * 60)
        print("ERROR: Privileged Intents Required")
        print("=" * 60)
        print("\nThe bot requires privileged intents that must be enabled")
        print("in the Discord Developer Portal.\n")
        print("Required intents:")
        print("  - Server Members Intent (PRIVILEGED)")
        print("  - Message Content Intent (PRIVILEGED)")
        print("  - Presence Intent (PRIVILEGED, recommended)")
        print("\nTo enable:")
        print("1. Go to: https://discord.com/developers/applications/")
        print("2. Select your application")
        print("3. Go to the 'Bot' section")
        print("4. Enable 'SERVER MEMBERS INTENT' under Privileged Gateway Intents")
        print("5. Enable 'MESSAGE CONTENT INTENT' under Privileged Gateway Intents")
        print("6. Enable 'PRESENCE INTENT' (ticket auto-assign + online stats)")
        print("7. Save changes and restart the bot")
        print("=" * 60 + "\n")
        raise
    except KeyboardInterrupt:
        print("\n[shutdown] Bot stopped by user")
    except Exception as e:
        print(f"\n[error] Bot crashed: {e}")
        raise
