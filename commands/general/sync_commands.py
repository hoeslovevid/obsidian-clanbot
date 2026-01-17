"""Sync commands command - forces a command sync (mods only)."""
import discord
from discord import app_commands

from utils import is_mod


def setup(bot):
    """Register the sync_commands command."""
    @bot.tree.command(name="sync_commands", description="Force sync bot commands (mods only, for debugging).")
    async def sync_commands(interaction: discord.Interaction):
        """Force sync commands to Discord."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get commands from the tree directly (before sync)
            # Use walk_commands() to get all commands recursively
            all_commands = []
            for cmd in bot.tree.walk_commands():
                if isinstance(cmd, app_commands.Command):
                    all_commands.append(cmd.name)
            
            # Remove duplicates and sort
            command_list = sorted(set(all_commands))
            
            # Sync commands
            if interaction.guild:
                guild_obj = discord.Object(id=interaction.guild.id)
                synced = await bot.tree.sync(guild=guild_obj)
            else:
                synced = await bot.tree.sync()
            
            # Build response
            if command_list:
                command_list_str = ', '.join(command_list)
            else:
                command_list_str = "No commands found"
            
            await interaction.followup.send(
                f"✅ Commands synced!\n\n"
                f"**Commands registered:** {len(command_list)}\n"
                f"**Command list:** {command_list_str}\n\n"
                f"Please wait 1-2 minutes for Discord to update, then refresh (Ctrl+R / Cmd+R).",
                ephemeral=True,
            )
        except Exception as e:
            import traceback
            error_msg = f"❌ Failed to sync commands: {e}\n\n```\n{traceback.format_exc()}\n```"
            # Truncate if too long
            if len(error_msg) > 2000:
                error_msg = error_msg[:1900] + "... (truncated)"
            await interaction.followup.send(
                error_msg,
                ephemeral=True,
            )
