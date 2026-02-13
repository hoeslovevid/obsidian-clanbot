"""Economy configuration (moderators only)."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod, EMBED_COLORS
from database import get_guild_setting, set_guild_setting


def setup(bot, group=None):
    """Register economy config command."""
    command_decorator = (
        group.command(name="config", description="Configure economy settings (moderators only).")
        if group
        else bot.tree.command(name="config", description="Configure economy settings (moderators only).")
    )

    @command_decorator
    @app_commands.describe(
        transfer_confirm_threshold="Coins threshold above which transfers require confirmation (0=always confirm, default 1000)",
    )
    async def economy_config(
        interaction: discord.Interaction,
        transfer_confirm_threshold: Optional[int] = None,
    ):
        """Configure economy settings."""
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Moderators only.", ephemeral=True)

        lines = []
        if transfer_confirm_threshold is not None:
            val = max(0, transfer_confirm_threshold)
            await set_guild_setting(interaction.guild.id, "transfer_confirm_threshold", str(val))
            lines.append(f"**Transfer confirmation:** Transfers of **{val:,}+** coins will require confirmation.")
        else:
            current = await get_guild_setting(interaction.guild.id, "transfer_confirm_threshold")
            thresh = int(current) if current and str(current).isdigit() else 1000
            lines.append(f"**Transfer confirmation:** Currently **{thresh:,}+** coins (set `transfer_confirm_threshold` to change).")

        await interaction.response.send_message(
            embed=obsidian_embed("⚙️ Economy Config", "\n".join(lines), color=EMBED_COLORS["economy"], client=interaction.client),
            ephemeral=True,
        )
