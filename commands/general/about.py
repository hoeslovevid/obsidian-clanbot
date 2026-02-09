"""About command - bot description, features, and developer info."""
import discord
from discord import app_commands

from utils import obsidian_embed
from config import BOT_VERSION, BOT_WEBSITE, BOT_DEVELOPER


def setup(bot, group=None):
    """Register the about command."""
    command_decorator = (
        group.command(name="about", description="Learn about the bot, its features, and developer.")
        if group
        else bot.tree.command(name="about", description="Learn about the bot, its features, and developer.")
    )

    @command_decorator
    async def about(interaction: discord.Interaction):
        """Display bot description, main features, and developer info."""
        desc = (
            "A versatile Discord bot for community management with voice channels, "
            "complaints, events, economy, moderation, and more."
        )

        features = (
            "• **Voice** – Join-to-create temp channels, controls (rename, limit, lock)\n"
            "• **Complaints** – File complaints with staff threading\n"
            "• **Events** – Create events with RSVP and reminders\n"
            "• **Economy** – Coins, XP, levels, shop, pets, achievements\n"
            "• **Moderation** – Purge, warn, automod, reaction roles, logging\n"
            "• **Community** – Tickets, suggestions, applications, giveaways\n"
            "• **Warframe** – Baro, cycles, alerts, LFG, link account\n"
            "• **Trading** – Trading post and price lookup"
        )

        fields = [
            ("📋 Main Features", features, False),
            ("📌 Version", BOT_VERSION or "—", True),
        ]

        if BOT_DEVELOPER:
            fields.append(("👤 Developer", BOT_DEVELOPER, True))

        embed = obsidian_embed(
            "About",
            desc,
            color=discord.Color.blurple(),
            fields=fields,
            client=interaction.client,
        )

        if BOT_WEBSITE:
            embed.add_field(name="🌐 Website", value=f"[Visit]({BOT_WEBSITE})", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)
