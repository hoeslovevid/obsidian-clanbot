"""Set optional guild-specific embed footer text."""
from __future__ import annotations

import discord
from discord import app_commands

from core.guild_branding import set_guild_embed_footer
from core.utils import is_mod, success_embed


def setup(bot, group=None):
    command_decorator = (
        group.command(name="branding", description="Set a short custom footer on bot embeds in this server.")
        if group
        else bot.tree.command(name="branding", description="Set custom embed footer for this server.")
    )

    @command_decorator
    @app_commands.describe(footer="Short suffix (e.g. clan tag). Leave empty to clear.")
    async def branding(interaction: discord.Interaction, footer: str | None = None):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import reply_mods_only
            return await reply_mods_only(interaction)
        await set_guild_embed_footer(interaction.guild.id, footer)
        try:
            from core.guild_branding import get_guild_embed_footer
            await get_guild_embed_footer(interaction.guild.id)
        except Exception:
            pass
        if footer and footer.strip():
            msg = f"Footer set to: _{footer.strip()[:120]}_"
        else:
            msg = "Custom footer cleared."
        await interaction.response.send_message(
            embed=success_embed("Guild branding", msg, client=interaction.client),
            ephemeral=True,
        )
