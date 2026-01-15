"""Update log command for moderators to post bot updates."""
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
    """Register the update_log command."""
    @bot.tree.command(name="update_log", description="Post a bot update log (moderators only).")
    @app_commands.describe(
        title="Title of the update (e.g., 'New Command Added')",
        description="Description of the update (what was added/changed)",
        version="Optional version number or date"
    )
    async def update_log(
        interaction: discord.Interaction,
        title: str,
        description: str,
        version: str = None
    ):
        """Post an update log to the configured channel."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can use this command.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
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
        
        # Create update log embed
        fields = [
            ("Update", description, False),
        ]
        
        if version:
            fields.append(("Version", version, True))
        
        fields.append(("Posted By", interaction.user.mention, True))
        fields.append(("Date", f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", True))
        
        embed = obsidian_embed(
            f"🔔 Bot Update: {title}",
            "",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        # Set timestamp
        embed.timestamp = datetime.now(timezone.utc)
        
        try:
            await channel.send(embed=embed)
            
            # If version is provided, mark it as posted (so automatic updates don't repost it)
            # Also update the stored version in bot_version_tracking to match
            if version:
                async with aiosqlite.connect(DB_PATH) as db:
                    # Mark as posted for this guild
                    await db.execute("""
                        INSERT OR REPLACE INTO update_log_posted_versions (guild_id, version, posted_at)
                        VALUES (?, ?, ?)
                    """, (interaction.guild.id, version, datetime.now(timezone.utc).isoformat()))
                    
                    # Update the stored version and hash to match this manual update
                    current_hash = calculate_feature_hash(interaction.client)
                    await db.execute("""
                        INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated)
                        VALUES (1, ?, ?, ?)
                    """, (version, current_hash, datetime.now(timezone.utc).isoformat()))
                    await db.commit()
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Update Log Posted",
                    f"Update log has been posted to {channel.mention}.",
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
            logging.getLogger(__name__).error(f"Error posting update log: {e}")
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    f"Failed to post update log: {str(e)}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
