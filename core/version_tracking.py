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
    
    # Get all commands (both global and guild-specific), including subcommands from groups
    try:
        import os
        GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            top_level_commands = bot.tree.get_commands(guild=guild)
        else:
            top_level_commands = bot.tree.get_commands(guild=None)
        
        # Recursively get all commands including subcommands
        commands_list = sorted(get_all_commands_recursive(top_level_commands))
        logger.info(f"[version] Calculated hash from {len(commands_list)} commands (including subcommands): {', '.join(commands_list[:10])}{'...' if len(commands_list) > 10 else ''}")
    except Exception as e:
        logger.error(f"[version] Error getting commands: {e}", exc_info=True)
        return ""
    
    # Create hash from sorted command list
    commands_str = ",".join(commands_list)
    
    # Also include hash of key bot files to detect code changes
    file_hashes = []
    key_files = ["bot.py", "database.py", "warframe_api.py", "tasks.py", "utils.py", "views.py"]
    
    # Get the directory where bot.py is located
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    
    for filename in key_files:
        filepath = os.path.join(bot_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, 'rb') as f:
                    file_content = f.read()
                    file_hash = hashlib.md5(file_content).hexdigest()[:8]  # First 8 chars
                    file_hashes.append(f"{filename}:{file_hash}")
                    logger.debug(f"[version] Hashed {filename}: {file_hash}")
            except Exception as e:
                logger.warning(f"[version] Could not hash {filename}: {e}")
        else:
            logger.debug(f"[version] File not found for hashing: {filepath}")
    
    # Combine commands and file hashes
    combined_str = commands_str + "|" + "|".join(file_hashes)
    hash_value = hashlib.md5(combined_str.encode()).hexdigest()
    logger.info(f"[version] Feature hash: {hash_value[:8]}... (from {len(commands_list)} commands + {len(file_hashes)} files)")
    return hash_value


async def detect_and_update_version(bot) -> Tuple[str, list]:
    """
    Detect if features have changed and auto-increment version.
    Returns: (version, list of changes)
    """
    import os
    GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")
    current_hash = calculate_feature_hash(bot)
    
    # Get current commands list for comparison (including subcommands from groups)
    current_commands = set()
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            top_level_commands = bot.tree.get_commands(guild=guild)
        else:
            top_level_commands = bot.tree.get_commands(guild=None)
        
        # Recursively get all commands including subcommands
        current_commands = set(get_all_commands_recursive(top_level_commands))
    except Exception:
        pass
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get stored version info and previous commands
        cur = await db.execute("""
            SELECT current_version, feature_hash, previous_commands FROM bot_version_tracking WHERE id = 1
        """)
        row = await cur.fetchone()
        
        if not row:
            # First time - initialize with version 1.2.0
            new_version = "1.2.0"
            changes = ["Initial bot version"]
            if current_commands:
                changes.append(f"**Commands:** {', '.join(sorted(current_commands))}")
            logger.info(f"[version] First run detected, initializing with version {new_version}")
            # Store current commands as previous_commands for next comparison
            current_commands_str = ",".join(sorted(current_commands)) if current_commands else ""
            await db.execute("""
                INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated, previous_commands)
                VALUES (1, ?, ?, ?, ?)
            """, (new_version, current_hash, datetime.now(timezone.utc).isoformat(), current_commands_str))
            await db.commit()
            
            # Verify the version was stored correctly
            verify_cur = await db.execute("SELECT current_version FROM bot_version_tracking WHERE id = 1")
            verify_row = await verify_cur.fetchone()
            if verify_row and verify_row[0] == new_version:
                logger.info(f"[version] ✅ Version {new_version} successfully stored and verified in database")
            else:
                logger.error(f"[version] ❌ Version storage verification failed! Expected {new_version}, got {verify_row}")
            
            return new_version, changes
        else:
            stored_version = row[0]
            stored_hash = row[1] if len(row) > 1 else ""
            previous_commands_str = row[2] if len(row) > 2 and row[2] else None
            
            # Reset version to 1.2.0 if stored version is less than 1.2.0
            try:
                version_parts = stored_version.split(".")
                if len(version_parts) >= 2:
                    major = int(version_parts[0])
                    minor = int(version_parts[1])
                    if major < 1 or (major == 1 and minor < 2):
                        logger.info(f"[version] Resetting version from {stored_version} to 1.2.0")
                        stored_version = "1.2.0"
                        # Update stored version
                        await db.execute("""
                            UPDATE bot_version_tracking 
                            SET current_version = ? 
                            WHERE id = 1
                        """, (stored_version,))
                        await db.commit()
            except (ValueError, IndexError):
                # Invalid version format, reset to 1.2.0
                logger.info(f"[version] Invalid version format {stored_version}, resetting to 1.2.0")
                stored_version = "1.2.0"
                await db.execute("""
                    UPDATE bot_version_tracking 
                    SET current_version = ? 
                    WHERE id = 1
                """, (stored_version,))
                await db.commit()
            
            logger.info(f"[version] Loaded stored version: {stored_version}, hash: {stored_hash[:8] if stored_hash else 'empty'}...")
            
            # Get previous commands from stored data (these are the commands from the LAST version)
            previous_commands = set()
            if previous_commands_str:
                try:
                    previous_commands = set(previous_commands_str.split(",")) if previous_commands_str else set()
                    logger.info(f"[version] Previous commands loaded: {len(previous_commands)} commands")
                except Exception as e:
                    logger.warning(f"[version] Error parsing previous commands: {e}")
                    previous_commands = set()
            else:
                logger.info(f"[version] No previous commands stored (first change detection)")
            
            # If hash hasn't changed, no update needed - return stored version with no changes
            if stored_hash == current_hash:
                logger.info(f"[version] No changes detected (hash: {current_hash[:8] if current_hash else 'empty'}...), keeping version {stored_version}")
                # Return stored version with empty changes list - this means no update needed
                return stored_version, []
            
            # Hash changed - detect what changed
            logger.info(f"[version] Hash changed from {stored_hash[:8] if stored_hash else 'empty'}... to {current_hash[:8]}...")
            changes = []
            
            # Compare commands to detect additions and removals
            logger.info(f"[version] Comparing commands: previous={len(previous_commands)}, current={len(current_commands)}")
            added_commands = current_commands - previous_commands
            removed_commands = previous_commands - current_commands
            
            logger.info(f"[version] Command changes detected: +{len(added_commands)} added, -{len(removed_commands)} removed")
            
            if added_commands:
                changes.append(f"✅ **Added {len(added_commands)} command(s):** {', '.join(sorted(added_commands))}")
            if removed_commands:
                changes.append(f"❌ **Removed {len(removed_commands)} command(s):** {', '.join(sorted(removed_commands))}")
            if not added_commands and not removed_commands and previous_commands:
                # Commands exist but changed in some way (maybe internal changes)
                changes.append("🔄 **Internal updates:** Commands or features have been modified")
            elif not previous_commands:
                # First time detecting changes - don't show all commands, just note it's the first change
                changes.append("🚀 **First feature update:** Bot features have been updated")
            
            # Commands have changed - increment version based on change type
            try:
                # Parse version (format: MAJOR.MINOR.PATCH)
                version_parts = stored_version.split(".")
                if len(version_parts) >= 2:
                    major = int(version_parts[0])
                    minor = int(version_parts[1])
                    patch = int(version_parts[2]) if len(version_parts) > 2 else 0
                    
                    # Determine if this is a "big" change (commands added/removed) or "small" change (internal updates only)
                    has_added = len(added_commands) > 0
                    has_removed = len(removed_commands) > 0
                    is_big_change = has_added or has_removed
                    
                    logger.info(f"[version] Change detection: added={has_added} ({len(added_commands)}), removed={has_removed} ({len(removed_commands)}), is_big={is_big_change}")
                    
                    if is_big_change:
                        # Big change: increment minor version (1.7.0 → 1.8.0)
                        minor += 1
                        patch = 0  # Reset patch
                        logger.info(f"[version] Big change detected (commands added/removed), incrementing minor version")
                    else:
                        # Small change: increment patch version (1.7.0 → 1.7.1)
                        patch += 1
                        logger.info(f"[version] Small change detected (internal updates only), incrementing patch version")
                    
                    new_version = f"{major}.{minor}.{patch}"
                else:
                    # Fallback: start at 1.2.0
                    new_version = "1.2.0"
            except (ValueError, IndexError):
                # Invalid version format, start at 1.2.0
                new_version = "1.2.0"
            
            # Update stored version, hash, and store CURRENT commands as previous_commands for next comparison
            current_commands_str = ",".join(sorted(current_commands)) if current_commands else ""
            await db.execute("""
                INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated, previous_commands)
                VALUES (1, ?, ?, ?, ?)
            """, (new_version, current_hash, datetime.now(timezone.utc).isoformat(), current_commands_str))
            await db.commit()
            
            # Verify the version was stored correctly
            verify_cur = await db.execute("SELECT current_version FROM bot_version_tracking WHERE id = 1")
            verify_row = await verify_cur.fetchone()
            if verify_row and verify_row[0] == new_version:
                logger.info(f"[version] ✅ Version {new_version} successfully stored and verified in database (from {stored_version})")
            else:
                logger.error(f"[version] ❌ Version storage verification failed! Expected {new_version}, got {verify_row}")
            
            logger.info(f"[version] Version incremented to {new_version} (from {stored_version}), stored {len(current_commands)} commands as previous_commands")
            return new_version, changes


async def check_and_post_updates(bot):
    """Check if bot version has changed and post update logs automatically."""
    from bot import BOT_VERSION, BOT_CHANGELOG
    from core.utils import obsidian_embed
    
    logger.info("[update_log] ========== Starting automatic update check ==========")
    
    # First, detect if version should be auto-updated
    detected_version, changes = await detect_and_update_version(bot)
    logger.info(f"[update_log] Version detection result: version={detected_version}, changes={len(changes) if changes else 0}")
    if changes:
        logger.info(f"[update_log] Changes detected: {changes}")
    
    # If no changes detected, don't post an update (version persists, no need to post)
    if not changes:
        logger.info(f"[update_log] No changes detected, version remains at {detected_version}, skipping update post")
        return
    
    # Use detected version (or fallback to env version)
    version_to_use = detected_version if detected_version else BOT_VERSION
    
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
