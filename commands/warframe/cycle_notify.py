"""Cycle notification settings command (moderators only)."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register the cycle_notify command."""
    command_decorator = group.command(name="cycle_notify", description="Configure open world cycle notifications (moderators only).") if group else bot.tree.command(name="cycle_notify", description="Configure open world cycle notifications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        cycle_type="Which cycle to configure",
        enabled="Enable or disable notifications",
        channel="Channel to send notifications to (leave empty to use current channel)",
        ping_role="Role to ping when cycle changes (optional; set/update anytime)"
    )
    @app_commands.choices(cycle_type=[
        app_commands.Choice(name="Cetus", value="cetus"),
        app_commands.Choice(name="Fortuna", value="vallis"),
        app_commands.Choice(name="Deimos", value="cambion"),
    ])
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def cycle_notify(
        interaction: discord.Interaction,
        cycle_type: app_commands.Choice[str],
        enabled: app_commands.Choice[str],
        channel: discord.TextChannel = None,
        ping_role: Optional[discord.Role] = None
    ):
        """Configure cycle notifications."""
        if not interaction.guild:
            return await interaction.response.send_message(
                "Cycle notifications can only be configured in a server.",
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
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
        
        # Get cycle display name (needed for messages)
        cycle_names = {
            'cetus': 'Cetus (Plains of Eidolon)',
            'vallis': 'Fortuna (Orb Vallis)',
            'cambion': 'Deimos (Cambion Drift)',
        }
        cycle_display = cycle_names.get(cycle_value, cycle_value)
        
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
            # Check if settings exist (include ping_role_id)
            cur = await db.execute(
                f"SELECT channel_id, {column}, ping_role_id FROM cycle_notification_settings WHERE guild_id=?",
                (interaction.guild.id,)
            )
            existing = await cur.fetchone()
            
            if existing:
                current_channel_id, current_enabled, current_ping_role_id = existing[0], existing[1], (existing[2] if len(existing) > 2 else None)
                
                # If only updating ping role (already enabled and ping_role provided)
                if is_enabled and current_enabled and ping_role is not None:
                    await db.execute(
                        "UPDATE cycle_notification_settings SET ping_role_id=? WHERE guild_id=?",
                        (ping_role.id, interaction.guild.id)
                    )
                    await db.commit()
                    embed = obsidian_embed(
                        "✅ Ping Role Updated",
                        f"Cycle notifications will now ping **{ping_role.mention}** when **{cycle_display}** (and any other enabled cycle) changes.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=False)
                
                # Clear ping role if explicitly set to None (e.g. by disabling)
                if is_enabled and current_enabled and ping_role is None and current_ping_role_id is not None:
                    # User might want to clear - we don't have "clear" option; only update when they pass a role
                    pass
                
                # Check if already enabled/disabled
                if is_enabled and current_enabled:
                    # Already enabled - show current settings
                    current_channel = interaction.guild.get_channel(current_channel_id) if current_channel_id else None
                    channel_mention = current_channel.mention if current_channel else f"<#{current_channel_id}>" if current_channel_id else "Not set"
                    ping_role_mention = "Not set"
                    if current_ping_role_id:
                        r = interaction.guild.get_role(int(current_ping_role_id))
                        ping_role_mention = r.mention if r else f"<@&{current_ping_role_id}>"
                    fields = [
                        ("📢 Status", "**Enabled**", True),
                        ("📢 Channel", channel_mention, True),
                        ("🔔 Ping Role", ping_role_mention, True),
                    ]
                    desc = f"**{cycle_display}** cycle notifications are already enabled.\n\nTo change the channel, disable and re-enable with a new channel.\nTo set or update the ping role, run this command again with **Enable** and choose a **ping_role**."
                    embed = obsidian_embed(
                        "ℹ️ Already Enabled",
                        desc,
                        color=discord.Color.blue(),
                        fields=fields,
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=False)
                
                if not is_enabled and not current_enabled:
                    # Already disabled
                    embed = obsidian_embed(
                        "ℹ️ Already Disabled",
                        f"**{cycle_display}** cycle notifications are already disabled.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=False)
                
                # If enabling, update channel and optionally ping role. If disabling, keep existing channel and role.
                new_channel_id = target_channel.id if is_enabled else (current_channel_id or target_channel.id)
                new_ping_role_id = (ping_role.id if ping_role else current_ping_role_id) if is_enabled else current_ping_role_id
                
                # Update existing settings
                await db.execute(f"""
                    UPDATE cycle_notification_settings
                    SET channel_id=?, {column}=?, ping_role_id=?
                    WHERE guild_id=?
                """, (new_channel_id, 1 if is_enabled else 0, new_ping_role_id, interaction.guild.id))
            else:
                # Create new settings (only if enabling)
                if is_enabled:
                    cetus_val = 1 if (cycle_value == 'cetus') else 0
                    fortuna_val = 1 if (cycle_value == 'vallis') else 0
                    deimos_val = 1 if (cycle_value == 'cambion') else 0
                    ping_role_id = ping_role.id if ping_role else None
                    await db.execute("""
                        INSERT INTO cycle_notification_settings (guild_id, channel_id, cetus_enabled, fortuna_enabled, deimos_enabled, ping_role_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (interaction.guild.id, target_channel.id, cetus_val, fortuna_val, deimos_val, ping_role_id))
                else:
                    # Can't disable something that doesn't exist
                    return await interaction.response.send_message(
                        "This cycle notification is not currently enabled. Use 'Enable' to set it up first.",
                        ephemeral=True
                    )
            
            await db.commit()
        
        status = "enabled" if is_enabled else "disabled"
        if is_enabled:
            ping_role_mention = ping_role.mention if ping_role else "Not set"
        else:
            async with aiosqlite.connect(DB_PATH) as db2:
                cur = await db2.execute("SELECT ping_role_id FROM cycle_notification_settings WHERE guild_id=?", (interaction.guild.id,))
                row = await cur.fetchone()
                pid = row[0] if row and row[0] else None
            if pid:
                r = interaction.guild.get_role(int(pid))
                ping_role_mention = r.mention if r else f"<@&{pid}>"
            else:
                ping_role_mention = "Not set"
        
        fields = [
            ("📢 Status", f"**{status.title()}**", True),
            ("📢 Channel", target_channel.mention, True),
            ("🔔 Ping Role", ping_role_mention, True),
        ]
        
        desc = f"**{cycle_display}** cycle notifications are now **{status}**."
        if is_enabled:
            desc += "\n\nWhen the cycle changes, a notification will be sent to this channel."
            if ping_role:
                desc += f" **{ping_role.mention}** will be pinged."
        else:
            desc += "\n\nNotifications for this cycle will no longer be sent."
        
        embed = obsidian_embed(
            "✅ Cycle Notifications Updated",
            desc,
            color=discord.Color.green() if is_enabled else discord.Color.orange(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
