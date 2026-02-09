"""Sync commands command - forces a command sync (mods only)."""
import discord  # type: ignore
from discord import app_commands  # type: ignore

from utils import is_mod, obsidian_embed


def setup(bot, group=None):
    """Register the sync_commands command."""
    command_decorator = group.command(name="sync_commands", description="Force sync bot commands (mods only, for debugging).") if group else bot.tree.command(name="sync_commands", description="Force sync bot commands (mods only, for debugging).")
    
    @command_decorator
    async def sync_commands(interaction: discord.Interaction):
        """Force sync commands to Discord."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Sync commands
            if interaction.guild:
                guild_obj = discord.Object(id=interaction.guild.id)
                await bot.tree.sync(guild=guild_obj)
            else:
                await bot.tree.sync()
            
            # Build group -> count from tree (after sync)
            by_group = {}
            for cmd in bot.tree.walk_commands():
                if isinstance(cmd, app_commands.Command):
                    parent = cmd.parent
                    group_name = parent.name if parent and isinstance(parent, app_commands.Group) else "root"
                    by_group[group_name] = by_group.get(group_name, 0) + 1
            
            total = sum(by_group.values())
            lines = [f"**{g}:** {c} command(s)" for g, c in sorted(by_group.items())]
            
            embed = obsidian_embed(
                "✅ Commands Synced",
                f"**Registered:** {total} command(s)\n\n" + "\n".join(lines) + "\n\n"
                "_Discord may take 1–2 minutes to update. Refresh (Ctrl+R) if commands don't appear._",
                color=discord.Color.green(),
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            import traceback
            error_msg = str(e)
            if len(error_msg) > 1000:
                error_msg = error_msg[:1000] + "..."
            await interaction.followup.send(
                embed=obsidian_embed("❌ Sync Failed", f"```\n{error_msg}\n```", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
