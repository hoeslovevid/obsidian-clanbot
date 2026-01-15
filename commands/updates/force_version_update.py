"""Force version update command for moderators to manually trigger version updates."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot):
    """Register the force_version_update command."""
    @bot.tree.command(name="force_version_update", description="Force post the most recent bot update to Discord (moderators only).")
    async def force_version_update(interaction: discord.Interaction):
        """Force post the most recent detected update to the update log channel."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can use this command.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Get update log channel
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT channel_id FROM update_log_settings WHERE guild_id = ?
            """, (interaction.guild.id,))
            row = await cur.fetchone()
        
        if not row or not row[0]:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Update Log Channel Not Set",
                    "Please configure an update log channel first using `/update_log_setup`.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        channel_id = row[0]
        channel = interaction.guild.get_channel(channel_id)
        
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Channel Not Found",
                    "The configured update log channel no longer exists. Please reconfigure using `/update_log_setup`.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Get current version and check if it's already posted
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT current_version, previous_commands FROM bot_version_tracking WHERE id = 1
            """)
            row = await cur.fetchone()
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Version Found",
                        "No version information found. The bot may need to restart first.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            current_version = row[0]
            previous_commands_str = row[1] if len(row) > 1 and row[1] else None
            
            # Check if this version has already been posted
            cur = await db.execute("""
                SELECT 1 FROM update_log_posted_versions 
                WHERE guild_id = ? AND version = ?
            """, (interaction.guild.id, current_version))
            already_posted = await cur.fetchone()
        
        # Detect changes automatically by comparing with previous version
        from bot import GUILD_ID, detect_and_update_version
        detected_version, detected_changes = await detect_and_update_version(interaction.client)
        
        # Get current commands for comparison
        current_commands = set()
        try:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                current_commands = set(cmd.name for cmd in interaction.client.tree.get_commands(guild=guild))
            else:
                current_commands = set(cmd.name for cmd in interaction.client.tree.get_commands(guild=None))
        except Exception:
            pass
        
        # Compare with previous commands
        previous_commands = set()
        if previous_commands_str:
            try:
                previous_commands = set(previous_commands_str.split(",")) if previous_commands_str else set()
            except Exception:
                pass
        
        added_commands = current_commands - previous_commands
        removed_commands = previous_commands - current_commands
        
        # Build git-style commit summary (same format as automatic updates)
        from bot import BOT_CHANGELOG
        
        # Parse changes into categories
        parsed_added = []
        parsed_removed = []
        other_changes = []
        
        # Parse detected changes
        for change in detected_changes:
            if "✅ **Added" in change or "Added" in change:
                if "command(s):" in change:
                    cmd_list = change.split("command(s):")[-1].strip()
                    parsed_added.extend([cmd.strip() for cmd in cmd_list.split(",")])
            elif "❌ **Removed" in change or "Removed" in change:
                if "command(s):" in change:
                    cmd_list = change.split("command(s):")[-1].strip()
                    parsed_removed.extend([cmd.strip() for cmd in cmd_list.split(",")])
            else:
                other_changes.append(change)
        
        # Also use direct command comparison as fallback
        if not parsed_added and added_commands:
            parsed_added = sorted(added_commands)
        if not parsed_removed and removed_commands:
            parsed_removed = sorted(removed_commands)
        
        # Build summary
        summary_parts = []
        
        # Main summary from BOT_CHANGELOG if available
        if BOT_CHANGELOG:
            summary_parts.append(f"**Summary:**\n{BOT_CHANGELOG}")
        
        # Build changes summary
        changes_summary = []
        
        if parsed_added:
            changes_summary.append(f"**Added ({len(parsed_added)}):**\n" + "\n".join([f"  + `{cmd}`" for cmd in sorted(parsed_added)]))
        
        if parsed_removed:
            changes_summary.append(f"**Removed ({len(parsed_removed)}):**\n" + "\n".join([f"  - `{cmd}`" for cmd in sorted(parsed_removed)]))
        
        if other_changes:
            for change in other_changes:
                clean_change = change.replace("**", "").replace("🔄", "").replace("🚀", "").strip()
                if clean_change:
                    changes_summary.append(f"**Modified:**\n  {clean_change}")
        
        # Combine summary
        if summary_parts:
            description = "\n\n".join(summary_parts)
        else:
            description = f"**Update Summary:**\nBot updated to version {current_version}"
        
        if changes_summary:
            description += "\n\n" + "\n\n".join(changes_summary)
        
        # If no changes detected
        if not changes_summary and not BOT_CHANGELOG:
            description = f"Bot has been updated to version {current_version}."
        
        # Force post the current version by temporarily removing it from posted versions
        # if it was already posted, so it will be posted again
        if already_posted:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    DELETE FROM update_log_posted_versions 
                    WHERE guild_id = ? AND version = ?
                """, (interaction.guild.id, current_version))
                await db.commit()
        
        # Create update log embed
        fields = [
            ("Changelog", description, False),
            ("Version", current_version, True),
            ("Posted By", interaction.user.mention, True),
            ("Date", f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", True),
        ]
        
        embed = obsidian_embed(
            f"🔔 Bot Update: Bot Updated to v{current_version}",
            "",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        # Set timestamp
        embed.timestamp = datetime.now(timezone.utc)
        
        try:
            await channel.send(embed=embed)
            
            # Mark this version as posted for this guild
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO update_log_posted_versions (guild_id, version, posted_at)
                    VALUES (?, ?, ?)
                """, (interaction.guild.id, current_version, datetime.now(timezone.utc).isoformat()))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Update Posted",
                    f"Current bot version **{current_version}** has been posted to {channel.mention}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    f"I don't have permission to send messages in {channel.mention}.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error posting version update: {e}")
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    f"Failed to post version update: {str(e)}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
