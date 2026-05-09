"""Update log setup command for moderators."""
import discord
from discord import app_commands
import logging

from core.utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore

logger = logging.getLogger(__name__)


def setup(bot, group=None):
    """Register the update_log_setup command."""
    command_decorator = group.command(name="update_log_setup", description="Configure the update log channel (moderators only).") if group else bot.tree.command(name="update_log_setup", description="Configure the update log channel (moderators only).")
    
    @command_decorator
    @app_commands.describe(channel="The channel where update logs will be posted (leave empty to disable)")
    async def update_log_setup(interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Configure the update log channel."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        
        if channel is None:
            # Disable update logs
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    DELETE FROM update_log_settings WHERE guild_id = ?
                """, (interaction.guild.id,))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Update Logs Disabled",
                    "Update logs have been disabled for this server.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        else:
            # Set update log channel
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO update_log_settings (guild_id, channel_id)
                    VALUES (?, ?)
                """, (interaction.guild.id, channel.id))
                await db.commit()
                # Verify the save worked
                cur = await db.execute("""
                    SELECT channel_id FROM update_log_settings WHERE guild_id = ?
                """, (interaction.guild.id,))
                verify = await cur.fetchone()
                if verify and verify[0] == channel.id:
                    logger.info(f"[update_log_setup] Successfully saved update log channel {channel.id} for guild {interaction.guild.id}")
                else:
                    logger.error(f"[update_log_setup] Failed to verify save of update log channel {channel.id} for guild {interaction.guild.id}")
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Update Log Channel Set",
                    f"Update logs will now be posted to {channel.mention}.\n\nUse `/update_log` to post new updates.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
