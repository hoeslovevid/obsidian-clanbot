"""Invasion notification configuration command."""
import discord
from discord import app_commands
import aiosqlite  # type: ignore

from utils import obsidian_embed, is_mod
from database import DB_PATH


def setup(bot, group=None):
    """Register the invasion_notify command."""
    command_decorator = group.command(name="invasion_notify", description="Configure invasion notifications (moderators only).") if group else bot.tree.command(name="invasion_notify", description="Configure invasion notifications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        reward="Reward to notify for (e.g., Fieldron, Detonite Injector, Mutagen Mass)",
        enabled="Enable or disable notifications",
        channel="Channel to send notifications to (required for enabling, optional for disabling)"
    )
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def invasion_notify(
        interaction: discord.Interaction,
        reward: str,
        enabled: app_commands.Choice[str],
        channel: discord.TextChannel = None
    ):
        """Configure invasion notifications for specific rewards."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        
        is_enabled = enabled.value == "enable"
        reward_lower = reward.lower().strip()
        
        # If enabling, require a channel
        if is_enabled:
            if not channel:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Channel Required",
                        "Please specify a channel to send notifications to when enabling.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            target_channel_id = channel.id
        else:
            # When disabling, check if settings exist
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT channel_id FROM invasion_notification_settings WHERE guild_id=? AND reward_lower=?",
                    (interaction.guild.id, reward_lower)
                )
                existing = await cur.fetchone()
                
                if not existing:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "ℹ️ Notifications Not Configured",
                            f"Notifications for **{reward}** are not currently configured for this server. Nothing to disable.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                target_channel_id = existing[0]  # Keep existing channel
        
        # Update database
        async with aiosqlite.connect(DB_PATH) as db:
            if is_enabled:
                # Check if already enabled
                cur = await db.execute(
                    "SELECT enabled FROM invasion_notification_settings WHERE guild_id=? AND reward_lower=?",
                    (interaction.guild.id, reward_lower)
                )
                existing = await cur.fetchone()
                
                if existing and existing[0]:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "ℹ️ Already Enabled",
                            f"Notifications for **{reward}** are already enabled.\n\n"
                            f"**Notification Channel:** <#{target_channel_id}>\n\n"
                            f"To change the channel, disable and re-enable with a new channel.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Insert or update
                await db.execute("""
                    INSERT INTO invasion_notification_settings (guild_id, reward_lower, reward_display, channel_id, enabled)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(guild_id, reward_lower) DO UPDATE SET
                        channel_id=?,
                        enabled=1,
                        reward_display=?
                """, (interaction.guild.id, reward_lower, reward, target_channel_id, target_channel_id, reward))
            else:
                # Disable
                await db.execute("""
                    UPDATE invasion_notification_settings
                    SET enabled=0
                    WHERE guild_id=? AND reward_lower=?
                """, (interaction.guild.id, reward_lower))
            
            await db.commit()
        
        fields = [
            ("📢 Status", f"**{'Enabled' if is_enabled else 'Disabled'}**", True),
            ("📢 Channel", f"<#{target_channel_id}>", True),
        ]
        
        if is_enabled:
            desc = f"**{reward}** invasion notifications are now **enabled**.\n\nWhen an invasion appears with this reward, a notification will be sent to this channel."
        else:
            desc = f"**{reward}** invasion notifications are now **disabled**.\n\nNotifications for this reward will no longer be sent."
        
        embed = obsidian_embed(
            "✅ Invasion Notifications Updated",
            desc,
            color=discord.Color.green() if is_enabled else discord.Color.orange(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
