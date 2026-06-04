"""
Version tracking and update logging.
This module handles automatic version detection and update posting.
"""
import logging
import hashlib
import os
from datetime import datetime, timezone
from typing import Tuple, List, Optional
import aiosqlite  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore

from database import DB_PATH, now_utc

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
    Returns: (canonical BOT_VERSION, list of changes for update-log posts)
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


async def check_and_post_updates(bot):
    """Check if bot version has changed and post update logs automatically."""
    from bot import BOT_VERSION, BOT_CHANGELOG
    from core.utils import obsidian_embed
    
    logger.info("[update_log] ========== Starting automatic update check ==========")
    
    # First, detect if version should be auto-updated
    detected_version, changes = await detect_and_update_version(bot)
    version_to_use = BOT_VERSION or detected_version
    bot._bot_version = version_to_use
    logger.info(
        "[update_log] Version detection result: version=%s, changes=%s",
        version_to_use,
        len(changes) if changes else 0,
    )
    if changes:
        logger.info(f"[update_log] Changes detected: {changes}")

    if not changes:
        logger.info(
            "[update_log] No changes detected, version remains at %s, skipping update post",
            version_to_use,
        )
        return
    
    if not version_to_use:
        logger.warning("[update_log] No version set, skipping update check")
        return  # No version set, skip
    
    logger.info(f"[update_log] Version changed to {version_to_use}, posting update with {len(changes)} change(s)")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get all guilds with update log channels configured
        cur = await db.execute("""
            SELECT guild_id, channel_id FROM update_log_settings WHERE channel_id IS NOT NULL
        """)
        guilds_with_logs = await cur.fetchall()
        logger.info(f"[update_log] Query result: {guilds_with_logs}")
    
    if not guilds_with_logs:
        logger.warning("[update_log] ⚠️ No update log channels configured in database! Use /update_log_setup to configure a channel.")
        return  # No update log channels configured
    
    logger.info(f"[update_log] Found {len(guilds_with_logs)} guild(s) with update log channels configured")
    
    for guild_id, channel_id in guilds_with_logs:
        try:
            guild = bot.get_guild(guild_id)
            if not guild:
                logger.warning(f"[update_log] Guild {guild_id} not found, skipping")
                continue
            
            channel = guild.get_channel(channel_id)
            if not channel:
                logger.warning(f"[update_log] Channel {channel_id} not found in guild {guild.name}, skipping")
                continue
            
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"[update_log] Channel {channel_id} in {guild.name} is not a text channel, skipping")
                continue
            
            # Verify bot has permission to send messages in this channel
            if not bot.user:
                logger.warning(f"[update_log] bot.user is None, skipping guild {guild.name}")
                continue
            
            bot_member = guild.get_member(bot.user.id)
            if not bot_member:
                logger.warning(f"[update_log] Bot member not found in guild {guild.name}, skipping")
                continue
            
            permissions = channel.permissions_for(bot_member)
            if not permissions.send_messages or not permissions.embed_links:
                logger.warning(f"[update_log] Bot lacks permissions (send_messages={permissions.send_messages}, embed_links={permissions.embed_links}) in {guild.name} (#{channel.name}), skipping")
                continue
            
            logger.info(f"[update_log] Verified channel {guild.name} (#{channel.name}) - has permissions, proceeding...")
            
            # Check if this version has already been posted
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT 1 FROM update_log_posted_versions 
                    WHERE guild_id = ? AND version = ?
                """, (guild_id, version_to_use))
                already_posted = await cur.fetchone()
            
            if already_posted:
                if changes:
                    # Version was posted before, but changes were just detected - this means version was just incremented
                    # Post it again to notify about the new version
                    logger.info(f"[update_log] ⚠️ Version {version_to_use} was posted before, but NEW CHANGES detected - will post update anyway")
                else:
                    # Already posted and no new changes - skip
                    logger.info(f"[update_log] Version {version_to_use} already posted to {guild.name} (#{channel.name}) and no new changes, skipping")
                    continue
            else:
                logger.info(f"[update_log] Version {version_to_use} not yet posted to {guild.name} (#{channel.name}), will post now")
            
            logger.info(f"[update_log] Version {version_to_use} not yet posted to {guild.name} (#{channel.name}), posting now...")
            
            # Build git-style commit summary
            added_commands = []
            removed_commands = []
            other_changes = []
            
            for change in changes:
                if "✅ **Added" in change or "Added" in change:
                    # Extract command names
                    if "command(s):" in change:
                        cmd_list = change.split("command(s):")[-1].strip()
                        added_commands.extend([cmd.strip() for cmd in cmd_list.split(",")])
                elif "❌ **Removed" in change or "Removed" in change:
                    if "command(s):" in change:
                        cmd_list = change.split("command(s):")[-1].strip()
                        removed_commands.extend([cmd.strip() for cmd in cmd_list.split(",")])
                else:
                    other_changes.append(change)
            
            # Build summary (like git commit message)
            summary_parts = []
            
            # Main summary from BOT_CHANGELOG if available
            if BOT_CHANGELOG:
                summary_parts.append(f"**Summary:**\n{BOT_CHANGELOG}")
            
            # Build changes summary
            changes_summary = []
            
            if added_commands:
                changes_summary.append(f"**Added ({len(added_commands)}):**\n" + "\n".join([f"  + `{cmd}`" for cmd in sorted(added_commands)]))
            
            if removed_commands:
                changes_summary.append(f"**Removed ({len(removed_commands)}):**\n" + "\n".join([f"  - `{cmd}`" for cmd in sorted(removed_commands)]))
            
            if other_changes:
                # Clean up other changes (remove markdown formatting for cleaner display)
                for change in other_changes:
                    clean_change = change.replace("**", "").replace("🔄", "").replace("🚀", "").strip()
                    if clean_change:
                        changes_summary.append(f"**Modified:**\n  {clean_change}")
            
            # Combine summary
            if summary_parts:
                description = "\n\n".join(summary_parts)
            else:
                description = f"**Update Summary:**\nBot updated to version {version_to_use}"
            
            if changes_summary:
                description += "\n\n" + "\n\n".join(changes_summary)
            
            # If no changes detected but we're posting (shouldn't happen, but safety check)
            if not changes_summary and not BOT_CHANGELOG:
                description = f"Bot has been updated to version {version_to_use}."
                logger.warning(f"[update_log] No changelog or changes detected for version {version_to_use}, posting generic message")
            
            embed = obsidian_embed(
                f"🤖 Bot Update v{version_to_use}",
                description,
                color=discord.Color.blue(),
                client=bot,
            )
            embed.timestamp = now_utc()
            
            try:
                await channel.send(embed=embed)

                # DM users that opted into changelog DMs (Item 27).
                try:
                    from commands.general.whatsnew import get_changelog_subscribers
                    subscribers = await get_changelog_subscribers(guild_id)
                    sent = 0
                    for uid in subscribers:
                        try:
                            member = guild.get_member(uid)
                            if not member or member.bot:
                                continue
                            await member.send(embed=embed)
                            sent += 1
                        except (discord.Forbidden, discord.HTTPException):
                            continue
                    if subscribers:
                        logger.info(f"[update_log] DMed changelog v{version_to_use} to {sent}/{len(subscribers)} subscribers in {guild.name}")
                except Exception as dm_err:
                    logger.debug(f"[update_log] changelog DM step failed: {dm_err}")

                # Mark as posted
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO update_log_posted_versions (guild_id, version, posted_at)
                        VALUES (?, ?, ?)
                    """, (guild_id, version_to_use, now_utc().isoformat()))
                    await db.commit()
                
                logger.info(f"[update_log] ✅ Posted version {version_to_use} to {guild.name} (#{channel.name})")
            except Exception as e:
                logger.error(f"[update_log] ❌ Error posting update to {guild.name} (#{channel.name}): {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"[update_log] Error processing guild {guild_id}: {e}", exc_info=True)
    
    logger.info("[update_log] ========== Automatic update check completed ==========")
