"""Warn system commands."""
import discord
from discord import app_commands
from typing import Optional
import dateparser

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot, group=None):
    """Register warn commands."""
    
    command_decorator = group.command(name="warn", description="Warn a user (moderators only).") if group else bot.tree.command(name="warn", description="Warn a user (moderators only).")
    
    @command_decorator
    @app_commands.describe(user="User to warn", reason="Reason for the warning")
    async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
        """Warn a user."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
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
        
        if user.bot:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid User",
                    "You cannot warn bots.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        # Add warning
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (interaction.guild.id, user.id, interaction.user.id, reason, now_utc().isoformat()))
            await db.commit()
            
            # Get warning count
            cur = await db.execute("""
                SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, user.id))
            warning_count = (await cur.fetchone())[0]
            
            # Get warn settings
            cur = await db.execute("""
                SELECT max_warnings, action_after_max FROM warn_settings WHERE guild_id=?
            """, (interaction.guild.id,))
            settings_row = await cur.fetchone()
            max_warnings = settings_row[0] if settings_row else 3
            action = settings_row[1] if settings_row else "mute"
        
        # Check if max warnings reached
        if warning_count >= max_warnings:
            # Execute action
            if action == "mute":
                # Create mute role or use existing
                mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
                if not mute_role:
                    try:
                        mute_role = await interaction.guild.create_role(name="Muted", reason="Auto-created for warn system")
                        # Deny send messages in all channels
                        for channel in interaction.guild.channels:
                            try:
                                await channel.set_permissions(mute_role, send_messages=False, speak=False)
                            except:
                                pass
                    except discord.Forbidden:
                        pass
                
                if mute_role:
                    try:
                        await user.add_roles(mute_role, reason=f"Auto-muted after {warning_count} warnings")
                    except discord.Forbidden:
                        pass
            
            elif action == "kick":
                try:
                    await user.kick(reason=f"Auto-kicked after {warning_count} warnings")
                except discord.Forbidden:
                    pass
            
            elif action == "ban":
                try:
                    await user.ban(reason=f"Auto-banned after {warning_count} warnings", delete_message_days=0)
                except discord.Forbidden:
                    pass
        
        # Send DM to user
        try:
            dm_embed = obsidian_embed(
                f"⚠️ Warning in {interaction.guild.name}",
                f"**Reason:** {reason}\n**Warnings:** {warning_count}/{max_warnings}\n\n"
                f"{'⚠️ You have reached the maximum warnings!' if warning_count >= max_warnings else 'Please follow the server rules.'}",
                color=discord.Color.orange(),
                client=interaction.client,
            )
            await user.send(embed=dm_embed)
        except:
            pass
        
        # Send confirmation
        action_text = f" ({action} executed)" if warning_count >= max_warnings else ""
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ User Warned",
                f"**User:** {user.mention}\n**Reason:** {reason}\n**Warnings:** {warning_count}/{max_warnings}{action_text}",
                color=discord.Color.orange(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="warnings", description="View a user's warnings.") if group else bot.tree.command(name="warnings", description="View a user's warnings.")
    
    @command_decorator
    @app_commands.describe(user="User to check")
    async def warnings(interaction: discord.Interaction, user: discord.Member):
        """View user warnings."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT moderator_id, reason, created_at FROM warnings
                WHERE guild_id=? AND user_id=? ORDER BY created_at DESC
            """, (interaction.guild.id, user.id))
            warnings_list = await cur.fetchall()
            
            cur = await db.execute("""
                SELECT max_warnings FROM warn_settings WHERE guild_id=?
            """, (interaction.guild.id,))
            settings_row = await cur.fetchone()
            max_warnings = settings_row[0] if settings_row else 3
        
        if not warnings_list:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "⚠️ Warnings",
                    f"{user.mention} has no warnings.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        warnings_text = "\n".join([
            f"**{i+1}.** {reason} - <t:{int(dateparser.parse(created_at, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}).timestamp())}:R>"
            for i, (mod_id, reason, created_at) in enumerate(warnings_list)
        ])
        
        embed = obsidian_embed(
            f"⚠️ Warnings for {user.display_name}",
            f"**Total:** {len(warnings_list)}/{max_warnings}\n\n{warnings_text}",
            color=discord.Color.orange(),
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    command_decorator = group.command(name="warn_setup", description="Configure warn system (moderators only).") if group else bot.tree.command(name="warn_setup", description="Configure warn system (moderators only).")
    
    @command_decorator
    @app_commands.describe(max_warnings="Maximum warnings before action", action="Action to take after max warnings", mute_duration="Mute duration in minutes (if action is mute)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Mute", value="mute"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
    ])
    async def warn_setup(interaction: discord.Interaction, max_warnings: int, action: str, mute_duration: Optional[int] = None):
        """Configure warn system."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
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
        
        if max_warnings < 1:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Value",
                    "Maximum warnings must be at least 1.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO warn_settings (guild_id, max_warnings, action_after_max, mute_duration)
                VALUES (?, ?, ?, ?)
            """, (interaction.guild.id, max_warnings, action, mute_duration))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Warn System Configured",
                f"**Max Warnings:** {max_warnings}\n**Action:** {action}\n"
                f"{f'**Mute Duration:** {mute_duration} minutes' if action == 'mute' and mute_duration else ''}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
