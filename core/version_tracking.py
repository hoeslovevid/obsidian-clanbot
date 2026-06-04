"""
Version tracking for deploy and feature-hash detection.

Channel release posts use ``core.release_announce.announce_release_if_needed`` only.
This module updates ``bot_version_tracking`` and does not post to changelog channels.
"""
import logging
import hashlib
import os
from datetime import datetime, timezone
from typing import Tuple, List
import aiosqlite  # type: ignore
from discord import app_commands  # type: ignore

from database import DB_PATH

logger = logging.getLogger(__name__)


async def get_current_bot_version() -> str:
    """Canonical user-facing release version (``BOT_VERSION`` from config/env)."""
    from core.config import BOT_VERSION

    return BOT_VERSION or "unknown"


def get_registered_commands(bot) -> list:
    """Top-level commands from the global tree (guild-scoped lookup is empty for this bot)."""
    return bot.tree.get_commands(guild=None)


def get_all_commands_recursive(commands, prefix=""):
    """
    Recursively get all commands including subcommands from groups.
    Returns a list of command identifiers in format "group:subcommand" or just "command".
    """
    command_list = []
    for cmd in commands:
        if isinstance(cmd, app_commands.Group):
            # It's a group - add the group name and recursively get subcommands
            group_name = cmd.name
            full_name = f"{prefix}{group_name}" if prefix else group_name
            command_list.append(full_name)  # Add the group itself
            # Recursively get subcommands
            subcommands = get_all_commands_recursive(cmd.commands, prefix=f"{full_name}:")
            command_list.extend(subcommands)
        else:
            # It's a regular command
            full_name = f"{prefix}{cmd.name}" if prefix else cmd.name
            command_list.append(full_name)
    return command_list


def calculate_feature_hash(bot) -> str:
    """Calculate a hash of all registered commands and key bot files to detect changes."""
    commands_list = []
    
    # Get all commands from the global registration tree
    try:
        top_level_commands = get_registered_commands(bot)
        commands_list = sorted(get_all_commands_recursive(top_level_commands))
        logger.info(f"[version] Calculated hash from {len(commands_list)} commands (including subcommands): {', '.join(commands_list[:10])}{'...' if len(commands_list) > 10 else ''}")
    except Exception as e:
        logger.error(f"[version] Error getting commands: {e}", exc_info=True)
        return ""
    
    # Create hash from sorted command list
    commands_str = ",".join(commands_list)
    
    # Also include hash of key bot files to detect code changes
    file_hashes = []
    from core.config import PROJECT_ROOT

    key_files = [
        "bot/app.py",
        "database/__init__.py",
        "api/warframe_api.py",
        "tasks/__init__.py",
        "core/utils.py",
        "views/__init__.py",
    ]
    project_root = str(PROJECT_ROOT)

    for rel_path in key_files:
        filepath = os.path.join(project_root, rel_path)
        if os.path.exists(filepath):
            try:
                with open(filepath, 'rb') as f:
                    file_content = f.read()
                    file_hash = hashlib.md5(file_content).hexdigest()[:8]  # First 8 chars
                    file_hashes.append(f"{rel_path}:{file_hash}")
                    logger.debug(f"[version] Hashed {rel_path}: {file_hash}")
            except Exception as e:
                logger.warning(f"[version] Could not hash {rel_path}: {e}")
        else:
            logger.debug(f"[version] File not found for hashing: {filepath}")
    
    # Combine commands and file hashes
    combined_str = commands_str + "|" + "|".join(file_hashes)
    hash_value = hashlib.md5(combined_str.encode()).hexdigest()
    logger.info(f"[version] Feature hash: {hash_value[:8]}... (from {len(commands_list)} commands + {len(file_hashes)} files)")
    return hash_value


def _command_change_lines(
    previous_commands: set,
    current_commands: set,
) -> list[str]:
    """Build human-readable change lines when the feature hash shifts."""
    changes: list[str] = []
    added_commands = current_commands - previous_commands
    removed_commands = previous_commands - current_commands
    if added_commands:
        changes.append(
            f"✅ **Added {len(added_commands)} command(s):** {', '.join(sorted(added_commands))}"
        )
    if removed_commands:
        changes.append(
            f"❌ **Removed {len(removed_commands)} command(s):** {', '.join(sorted(removed_commands))}"
        )
    if not added_commands and not removed_commands and previous_commands:
        changes.append("🔄 **Internal updates:** Commands or features have been modified")
    elif not previous_commands and current_commands:
        changes.append("🚀 **Feature update:** Bot commands or code have been updated")
    return changes


async def detect_and_update_version(bot) -> Tuple[str, list]:
    """
    Sync tracking DB to ``BOT_VERSION`` and detect deploy/feature changes.
    Returns: (canonical BOT_VERSION, list of change lines for logs only)
    """
    from core.config import BOT_VERSION

    canonical = (BOT_VERSION or "").strip() or "unknown"
    current_hash = calculate_feature_hash(bot)

    current_commands: set = set()
    try:
        top_level_commands = get_registered_commands(bot)
        current_commands = set(get_all_commands_recursive(top_level_commands))
    except Exception:
        pass

    current_commands_str = ",".join(sorted(current_commands)) if current_commands else ""
    now_iso = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT current_version, feature_hash, previous_commands FROM bot_version_tracking WHERE id = 1
        """)
        row = await cur.fetchone()

        if not row:
            changes: list[str] = []
            logger.info("[version] First run — initializing tracking at BOT_VERSION %s", canonical)
            await db.execute("""
                INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated, previous_commands)
                VALUES (1, ?, ?, ?, ?)
            """, (canonical, current_hash, now_iso, current_commands_str))
            await db.commit()
            return canonical, changes

        stored_version = (row[0] or "").strip()
        stored_hash = row[1] if len(row) > 1 else ""
        previous_commands_str = row[2] if len(row) > 2 and row[2] else ""

        previous_commands: set = set()
        if previous_commands_str:
            try:
                previous_commands = set(previous_commands_str.split(","))
            except Exception as e:
                logger.warning("[version] Error parsing previous commands: %s", e)

        version_changed = stored_version != canonical
        hash_changed = stored_hash != current_hash
        changes = []

        if version_changed:
            changes.append(f"🚀 **Release:** Deployed v{canonical}")
            logger.info(
                "[version] BOT_VERSION changed %s → %s",
                stored_version or "(empty)",
                canonical,
            )

        if hash_changed:
            logger.info(
                "[version] Feature hash changed %s... → %s...",
                (stored_hash[:8] if stored_hash else "empty"),
                (current_hash[:8] if current_hash else "empty"),
            )
            changes.extend(_command_change_lines(previous_commands, current_commands))

        if version_changed or hash_changed:
            await db.execute("""
                INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated, previous_commands)
                VALUES (1, ?, ?, ?, ?)
            """, (canonical, current_hash, now_iso, current_commands_str))
            await db.commit()
            logger.info("[version] Tracking synced to BOT_VERSION %s", canonical)
            return canonical, changes

        logger.info("[version] No deploy or feature changes (BOT_VERSION %s)", canonical)
        return canonical, []


async def sync_version_tracking(bot) -> None:
    """Update version/hash tracking DB on startup (no changelog channel posts)."""
    from core.config import BOT_VERSION

    logger.info("[version] Syncing bot_version_tracking…")
    detected_version, changes = await detect_and_update_version(bot)
    version_to_use = BOT_VERSION or detected_version
    bot._bot_version = version_to_use
    if changes:
        logger.info(
            "[version] Tracking updated for %s (%s change line(s)); release post handled by release_announce",
            version_to_use,
            len(changes),
        )
    else:
        logger.info("[version] Tracking unchanged at %s", version_to_use)


async def check_and_post_updates(bot) -> None:
    """Backward-compatible alias — tracking only; does not post embeds."""
    await sync_version_tracking(bot)
