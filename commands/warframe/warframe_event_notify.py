"""Warframe event auto-creation settings command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot):
    """Register the warframe_event_notify command."""
    @bot.tree.command(name="warframe_event_notify", description="Enable/disable automatic Discord event creation for major Warframe updates (moderators only).")
    @app_commands.describe(
        enabled="Enable or disable automatic event creation"
    )
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def warframe_event_notify(
        interaction: discord.Interaction,
        enabled: app_commands.Choice[str]
    ):
        """Configure automatic Warframe event creation."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can use this command.",
                ephemeral=True
            )
        
        is_enabled = enabled.value == "enable"
        
        # Update database
        async with aiosqlite.connect(DB_PATH) as db:
            # Check if settings exist
            cur = await db.execute(
                "SELECT enabled FROM warframe_event_settings WHERE guild_id=?",
                (interaction.guild.id,)
            )
            existing = await cur.fetchone()
            
            if existing:
                current_enabled = bool(existing[0])
                
                # Check if already enabled/disabled
                if is_enabled and current_enabled:
                    embed = obsidian_embed(
                        "ℹ️ Already Enabled",
                        "Automatic Discord event creation for major Warframe updates is already enabled.\n\n"
                        "The bot will automatically create server events when major Warframe events are detected.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=False)
                
                if not is_enabled and not current_enabled:
                    embed = obsidian_embed(
                        "ℹ️ Already Disabled",
                        "Automatic Discord event creation for major Warframe updates is already disabled.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=False)
                
                # Update existing settings
                await db.execute("""
                    UPDATE warframe_event_settings
                    SET enabled=?
                    WHERE guild_id=?
                """, (1 if is_enabled else 0, interaction.guild.id))
            else:
                # Create new settings
                await db.execute("""
                    INSERT INTO warframe_event_settings (guild_id, enabled)
                    VALUES (?, ?)
                """, (interaction.guild.id, 1 if is_enabled else 0))
            
            await db.commit()
        
        status = "enabled" if is_enabled else "disabled"
        
        if is_enabled:
            desc = f"Automatic Discord event creation for major Warframe updates is now **{status}**.\n\n"
            desc += "The bot will automatically create server events when major Warframe events are detected.\n\n"
            desc += "**Note:** The bot needs the 'Manage Events' permission to create scheduled events."
        else:
            desc = f"Automatic Discord event creation for major Warframe updates is now **{status}**.\n\n"
            desc += "No new Discord events will be automatically created from Warframe events."
        
        embed = obsidian_embed(
            "✅ Warframe Event Settings Updated",
            desc,
            color=discord.Color.green() if is_enabled else discord.Color.orange(),
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
