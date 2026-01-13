"""Cycle notification settings command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from bot import DB_PATH
import aiosqlite


def setup(bot):
    """Register the cycle_notify command."""
    @bot.tree.command(name="cycle_notify", description="Configure open world cycle notifications (moderators only).")
    @app_commands.describe(
        cycle_type="Which cycle to configure",
        enabled="Enable or disable notifications",
        channel="Channel to send notifications to (leave empty to use current channel)"
    )
    @app_commands.choices(cycle_type=[
        app_commands.Choice(name="Cetus (Plains of Eidolon)", value="cetus"),
        app_commands.Choice(name="Fortuna (Orb Vallis)", value="vallis"),
        app_commands.Choice(name="Deimos (Cambion Drift)", value="cambion"),
    ])
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def cycle_notify(
        interaction: discord.Interaction,
        cycle_type: app_commands.Choice[str],
        enabled: app_commands.Choice[str],
        channel: discord.TextChannel = None
    ):
        """Configure cycle notifications."""
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
        cycle_value = cycle_type.value
        
        # Map cycle types to database columns
        column_map = {
            'cetus': 'cetus_enabled',
            'vallis': 'fortuna_enabled',
            'cambion': 'deimos_enabled',
        }
        
        column = column_map.get(cycle_value)
        if not column:
            return await interaction.response.send_message(
                "Invalid cycle type.",
                ephemeral=True
            )
        
        # Update database
        async with aiosqlite.connect(DB_PATH) as db:
            # Check if settings exist
            cur = await db.execute(
                "SELECT channel_id FROM cycle_notification_settings WHERE guild_id=?",
                (interaction.guild.id,)
            )
            existing = await cur.fetchone()
            
            if existing:
                # Update existing settings
                await db.execute(f"""
                    UPDATE cycle_notification_settings
                    SET channel_id=?, {column}=?
                    WHERE guild_id=?
                """, (target_channel.id, 1 if is_enabled else 0, interaction.guild.id))
            else:
                # Create new settings
                cetus_val = 1 if (cycle_value == 'cetus' and is_enabled) else 0
                fortuna_val = 1 if (cycle_value == 'vallis' and is_enabled) else 0
                deimos_val = 1 if (cycle_value == 'cambion' and is_enabled) else 0
                
                await db.execute("""
                    INSERT INTO cycle_notification_settings (guild_id, channel_id, cetus_enabled, fortuna_enabled, deimos_enabled)
                    VALUES (?, ?, ?, ?, ?)
                """, (interaction.guild.id, target_channel.id, cetus_val, fortuna_val, deimos_val))
            
            await db.commit()
        
        # Get cycle display name
        cycle_names = {
            'cetus': 'Cetus (Plains of Eidolon)',
            'vallis': 'Fortuna (Orb Vallis)',
            'cambion': 'Deimos (Cambion Drift)',
        }
        cycle_display = cycle_names.get(cycle_value, cycle_value)
        
        status = "enabled" if is_enabled else "disabled"
        embed = obsidian_embed(
            "✅ Cycle Notifications Updated",
            f"**{cycle_display}** cycle notifications are now **{status}**.\n\n"
            f"**Notification Channel:** {target_channel.mention}\n\n"
            f"When the cycle changes, a notification will be sent to this channel.",
            color=discord.Color.green() if is_enabled else discord.Color.orange(),
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
