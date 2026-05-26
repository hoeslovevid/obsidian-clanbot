"""Invite command - get the bot's invite link."""
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed
from core.config import BOT_WEBSITE


def setup(bot, group=None):
    """Register the invite command."""
    command_decorator = (
        group.command(name="invite", description="Get the bot invite link to add it to other servers.")
        if group
        else bot.tree.command(name="invite", description="Get the bot invite link to add it to other servers.")
    )

    @command_decorator
    async def invite(interaction: discord.Interaction):
        """Return the bot's OAuth2 invite URL."""
        client = interaction.client
        if not client.user:
            return await interaction.response.send_message("Bot user not available.", ephemeral=True)

        # Permission integer: send messages, embed, manage messages, moderate members, manage roles,
        # kick, ban, use slash commands, connect to voice, manage channels, etc.
        permissions = 277025508160
        scope = "bot%20applications.commands"
        url = f"https://discord.com/api/oauth2/authorize?client_id={client.user.id}&permissions={permissions}&scope={scope}"

        body = (
            f"[**Click here to add me to another server**]({url})\n\n"
            "• You need *Manage Server* permission to add bots.\n"
            "• This link **never expires** — you can bookmark it.\n"
            "• Permissions are pre-selected for full bot functionality."
        )
        if BOT_WEBSITE:
            body += f"\n• **Website:** {BOT_WEBSITE}"

        embed = obsidian_embed(
            "🔗 Invite Link",
            body,
            color=discord.Color.blurple(),
            client=client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
