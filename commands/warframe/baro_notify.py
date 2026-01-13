"""Baro notification settings command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from bot import DB_PATH
import aiosqlite


def setup(bot):
    """Register the baro_notify command."""
    @bot.tree.command(name="baro_notify", description="Configure Baro Ki'Teer arrival notifications (moderators only).")
    @app_commands.describe(
        enabled="Enable or disable Baro arrival notifications",
        channel="Channel to send notifications to (leave empty to use current channel)"
    )
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def baro_notify(
        interaction: discord.Interaction,
        enabled: app_commands.Choice[str],
        channel: discord.TextChannel = None
    ):
        """Configure Baro arrival notifications."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can use this command.",
                ephemeral=True
            )
        
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Invalid channel specified.",
                ephemeral=True
            )
        
        is_enabled = enabled.value == "enable"
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO baro_notification_settings (guild_id, channel_id, enabled)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    enabled = excluded.enabled
            """, (interaction.guild.id, target_channel.id, 1 if is_enabled else 0))
            await db.commit()
        
        status = "enabled" if is_enabled else "disabled"
        embed = obsidian_embed(
            "✅ Baro Notifications Updated",
            f"Baro Ki'Teer arrival notifications are now **{status}**.\n\n"
            f"**Notification Channel:** {target_channel.mention}\n\n"
            f"When Baro arrives, a notification will be sent to this channel with his inventory and location.",
            color=discord.Color.green() if is_enabled else discord.Color.orange(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
