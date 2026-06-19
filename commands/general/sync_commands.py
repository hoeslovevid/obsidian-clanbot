"""Force sync commands command - forces a command sync (mods only)."""
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.command_sync import format_sync_success_embed_body, sync_app_commands, sync_scope_description
from core.utils import is_mod, obsidian_embed


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
            sync_guild_id, stats = await sync_app_commands(bot)
            scope = sync_scope_description(sync_guild_id)
            tree_body = format_sync_success_embed_body(stats, guild_id=sync_guild_id)
            
            embed = obsidian_embed(
                "✅ Commands Synced",
                f"**Scope:** {scope}\n\n{tree_body}\n\n"
                "_Discord may take 1–2 minutes to update globally. Refresh (Ctrl+R) if commands don't appear._",
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
