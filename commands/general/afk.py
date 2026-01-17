"""AFK command."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed
from database import set_afk, remove_afk, get_afk_status


def setup(bot):
    """Register the afk command."""
    
    @bot.tree.command(name="afk", description="Set yourself as AFK (Away From Keyboard).")
    @app_commands.describe(reason="Reason for being AFK (optional)")
    async def afk(interaction: discord.Interaction, reason: Optional[str] = None):
        """Set or remove AFK status."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
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
        
        # Check if already AFK
        current_afk = await get_afk_status(interaction.guild.id, interaction.user.id)
        
        if current_afk:
            # Remove AFK
            await remove_afk(interaction.guild.id, interaction.user.id)
            
            # Update nickname if it starts with [AFK]
            if interaction.user.display_name.startswith("[AFK]"):
                try:
                    new_nick = interaction.user.display_name.replace("[AFK] ", "").replace("[AFK]", "").strip()
                    if not new_nick:
                        new_nick = None
                    await interaction.user.edit(nick=new_nick)
                except:
                    pass  # Can't edit nickname, that's okay
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ AFK Removed",
                    "You are no longer marked as AFK.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        else:
            # Set AFK
            await set_afk(interaction.guild.id, interaction.user.id, reason)
            
            # Update nickname to include [AFK]
            try:
                current_nick = interaction.user.display_name
                if not current_nick.startswith("[AFK]"):
                    new_nick = f"[AFK] {current_nick}"[:32]  # Discord nickname limit
                    await interaction.user.edit(nick=new_nick)
            except:
                pass  # Can't edit nickname, that's okay
            
            reason_text = f" Reason: {reason}" if reason else ""
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ AFK Set",
                    f"You are now marked as AFK.{reason_text}",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
