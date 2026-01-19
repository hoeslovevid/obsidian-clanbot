"""Baro notification settings command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from bot import DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register the baro_notify command."""
    command_decorator = group.command(name="baro_notify", description="Configure Baro Ki'Teer arrival notifications (moderators only).") if group else bot.tree.command(name="baro_notify", description="Configure Baro Ki'Teer arrival notifications (moderators only).")
    
    @command_decorator
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
                "Sorry, but you are not an Administrator in this server.",
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
        fields = [
            ("📢 Status", f"**{status.title()}**", True),
            ("📢 Channel", target_channel.mention, True),
        ]
        
        desc = "When Baro arrives, a notification will be sent with his inventory and location." if is_enabled else "Notifications will no longer be sent."
        
        embed = obsidian_embed(
            "✅ Baro Notifications Updated",
            desc,
            color=discord.Color.green() if is_enabled else discord.Color.orange(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
