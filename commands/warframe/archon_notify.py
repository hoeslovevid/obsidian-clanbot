"""Archon Hunt notification settings command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the archon_notify command."""
    command_decorator = group.command(name="archon_notify", description="Configure Archon Hunt notifications (moderators only).") if group else bot.tree.command(name="archon_notify", description="Configure Archon Hunt notifications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        enabled="Enable or disable notifications",
        channel="Channel to send notifications to (leave empty to use current channel)"
    )
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def archon_notify(
        interaction: discord.Interaction,
        enabled: app_commands.Choice[str],
        channel: discord.TextChannel = None
    ):
        """Configure Archon Hunt notifications."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        
        is_enabled = enabled.value == "enable"
        
        # If enabling, require a channel. If disabling, channel is optional.
        if is_enabled:
            target_channel = channel or interaction.channel
            if not isinstance(target_channel, discord.TextChannel):
                return await interaction.response.send_message(
                    "Please specify a valid channel to send notifications to when enabling.",
                    ephemeral=True
                )
        else:
            # When disabling, use existing channel or current channel (won't matter since it's disabled)
            target_channel = channel or interaction.channel
            if not isinstance(target_channel, discord.TextChannel):
                target_channel = interaction.channel  # Fallback to current channel
        
        # Update database
        async with aiosqlite.connect(DB_PATH) as db:
            # Check if settings exist
            cur = await db.execute(
                "SELECT channel_id, enabled FROM archon_notification_settings WHERE guild_id=?",
                (interaction.guild.id,)
            )
            existing = await cur.fetchone()
            
            if existing:
                current_channel_id, current_enabled = existing
                
                # Check if already enabled/disabled
                if is_enabled and current_enabled:
                    # Already enabled - show current settings
                    current_channel = interaction.guild.get_channel(current_channel_id) if current_channel_id else None
                    channel_mention = current_channel.mention if current_channel else f"<#{current_channel_id}>" if current_channel_id else "Not set"
                    
                    fields = [
                        ("📢 Status", "**Enabled**", True),
                        ("📢 Channel", channel_mention, True),
                    ]
                    
                    embed = obsidian_embed(
                        "ℹ️ Already Enabled",
                        "Archon Hunt notifications are already enabled.\n\nTo change the channel, disable and re-enable with a new channel.",
                        color=discord.Color.blue(),
                        fields=fields,
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=False)
                
                if not is_enabled and not current_enabled:
                    # Already disabled
                    embed = obsidian_embed(
                        "ℹ️ Already Disabled",
                        "Archon Hunt notifications are already disabled.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=False)
                
                # If enabling, update channel. If disabling, keep existing channel.
                new_channel_id = target_channel.id if is_enabled else (current_channel_id or target_channel.id)
                
                # Update existing settings
                await db.execute("""
                    UPDATE archon_notification_settings
                    SET channel_id=?, enabled=?
                    WHERE guild_id=?
                """, (new_channel_id, 1 if is_enabled else 0, interaction.guild.id))
            else:
                # Create new settings (only if enabling)
                if is_enabled:
                    await db.execute("""
                        INSERT INTO archon_notification_settings (guild_id, channel_id, enabled)
                        VALUES (?, ?, ?)
                    """, (interaction.guild.id, target_channel.id, 1))
                else:
                    # Can't disable something that doesn't exist
                    return await interaction.response.send_message(
                        "Archon Hunt notifications are not currently enabled. Use 'Enable' to set it up first.",
                        ephemeral=True
                    )
            
            await db.commit()
        
        status = "enabled" if is_enabled else "disabled"
        
        fields = [
            ("📢 Status", f"**{status.title()}**", True),
            ("📢 Channel", target_channel.mention, True),
        ]
        
        if is_enabled:
            desc = f"Archon Hunt notifications are now **{status}**.\n\nWhen a new Archon Hunt becomes available, a notification will be sent to this channel."
        else:
            desc = f"Archon Hunt notifications are now **{status}**.\n\nNotifications for Archon Hunts will no longer be sent."
        
        embed = obsidian_embed(
            "✅ Archon Hunt Notifications Updated",
            desc,
            color=discord.Color.green() if is_enabled else discord.Color.orange(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
