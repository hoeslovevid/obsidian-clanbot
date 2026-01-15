"""Force version update command for moderators to manually trigger version updates."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import hashlib

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def calculate_feature_hash(bot) -> str:
    """Calculate a hash of all registered commands to detect changes."""
    commands_list = []
    
    # Get all commands (both global and guild-specific)
    try:
        from bot import GUILD_ID
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            commands_list = sorted([cmd.name for cmd in bot.tree.get_commands(guild=guild)])
        else:
            commands_list = sorted([cmd.name for cmd in bot.tree.get_commands(guild=None)])
    except Exception:
        commands_list = []
    
    # Create hash from sorted command list
    commands_str = ",".join(commands_list)
    return hashlib.md5(commands_str.encode()).hexdigest()


def setup(bot):
    """Register the force_version_update command."""
    @bot.tree.command(name="force_version_update", description="Manually trigger a version update and post it (moderators only).")
    @app_commands.describe(
        description="Description of what changed in this update",
        version="Optional version number (e.g., '2.1.0'). If not provided, will auto-increment."
    )
    async def force_version_update(
        interaction: discord.Interaction,
        description: str,
        version: str = None
    ):
        """Manually trigger a version update and post it to the update log channel."""
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
        
        # Determine version to use
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT current_version FROM bot_version_tracking WHERE id = 1
            """)
            row = await cur.fetchone()
            stored_version = row[0] if row else "2.0.0"
        
        if version:
            new_version = version
        else:
            # Auto-increment version
            try:
                version_parts = stored_version.split(".")
                if len(version_parts) >= 2:
                    major = int(version_parts[0])
                    minor = int(version_parts[1])
                    patch = int(version_parts[2]) if len(version_parts) > 2 else 0
                    
                    # Increment minor version
                    minor += 1
                    patch = 0  # Reset patch
                    new_version = f"{major}.{minor}.{patch}"
                else:
                    new_version = f"{stored_version}.1"
            except (ValueError, IndexError):
                new_version = f"2.{int(datetime.now(timezone.utc).timestamp())}"
        
        # Update stored version and hash
        current_hash = calculate_feature_hash(interaction.client)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated)
                VALUES (1, ?, ?, ?)
            """, (new_version, current_hash, datetime.now(timezone.utc).isoformat()))
            await db.commit()
        
        # Create update log embed
        fields = [
            ("Update", description, False),
            ("Version", new_version, True),
            ("Posted By", interaction.user.mention, True),
            ("Date", f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", True),
        ]
        
        embed = obsidian_embed(
            f"🔔 Bot Update: Bot Updated to v{new_version}",
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
                """, (interaction.guild.id, new_version, datetime.now(timezone.utc).isoformat()))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Version Updated and Posted",
                    f"Version updated to **{new_version}** and posted to {channel.mention}.",
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
