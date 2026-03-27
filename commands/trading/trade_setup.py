"""Trading channel setup command for moderators."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the trade_setup command."""
    command_decorator = group.command(name="trade_setup", description="Configure the trading channel (moderators only).") if group else bot.tree.command(name="trade_setup", description="Configure the trading channel (moderators only).")
    
    @command_decorator
    @app_commands.describe(channel="The channel where trading posts will be sent (leave empty to use current channel)")
    async def trade_setup(interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Configure the trading channel."""
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
        
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Channel",
                    "Please specify a valid text channel.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO trading_channel_settings (guild_id, channel_id)
                VALUES (?, ?)
            """, (interaction.guild.id, target_channel.id))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Trading Channel Set",
                f"Trading posts will now be sent to {target_channel.mention}.\n\nUsers can use `/trade` to create listings.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
