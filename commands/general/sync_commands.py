"""Sync commands command - forces a command sync (mods only)."""
import discord

from utils import is_mod


def setup(bot):
    """Register the sync_commands command."""
    @bot.tree.command(name="sync_commands", description="Force sync bot commands (mods only, for debugging).")
    async def sync_commands(interaction: discord.Interaction):
        """Force sync commands to Discord."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get current commands before sync
            if interaction.guild:
                guild_obj = discord.Object(id=interaction.guild.id)
                commands_before = [cmd.name for cmd in bot.tree.get_commands(guild=guild_obj)]
                await bot.tree.sync(guild=guild_obj)
                commands_after = [cmd.name for cmd in bot.tree.get_commands(guild=guild_obj)]
            else:
                commands_before = [cmd.name for cmd in bot.tree.get_commands(guild=None)]
                await bot.tree.sync()
                commands_after = [cmd.name for cmd in bot.tree.get_commands(guild=None)]
            
            await interaction.followup.send(
                f"✅ Commands synced!\n\n"
                f"**Commands registered:** {len(commands_after)}\n"
                f"**Command list:** {', '.join(sorted(commands_after))}\n\n"
                f"Please wait 1-2 minutes for Discord to update, then refresh (Ctrl+R / Cmd+R).",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to sync commands: {e}",
                ephemeral=True,
            )
