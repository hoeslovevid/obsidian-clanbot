"""About command - bot description, features, and developer info."""
import aiosqlite  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed
from core.config import BOT_VERSION, BOT_WEBSITE, BOT_DEVELOPER
from database import DB_PATH


def setup(bot, group=None):
    """Register the about command."""
    command_decorator = (
        group.command(name="about", description="View bot info, features, version, and developer.")
        if group
        else bot.tree.command(name="about", description="View bot info, features, version, and developer.")
    )

    @command_decorator
    async def about(interaction: discord.Interaction):
        """Display bot description, main features, and developer info."""
        client = interaction.client
        bot_name = client.user.display_name if client.user else "Bot"

        # Read current version from database (updated on each deployment)
        version = BOT_VERSION or "—"
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT current_version FROM bot_version_tracking WHERE id = 1")
                row = await cur.fetchone()
                if row and row[0]:
                    version = str(row[0])
        except Exception:
            pass
        bot_avatar = (
            client.user.display_avatar.url
            if client.user and hasattr(client.user, "display_avatar")
            else (client.user.avatar.url if client.user and client.user.avatar else None)
        )

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
            ("📌 Version", version, True),
        ]
        if BOT_DEVELOPER:
            fields.append(("👤 Developer", BOT_DEVELOPER, True))
        if BOT_WEBSITE:
            fields.append(("🌐 Website", f"[Visit]({BOT_WEBSITE})", True))

        embed = obsidian_embed(
            f"About {bot_name}",
            desc,
            color=discord.Color.blurple(),
            author_name=bot_name,
            author_icon=bot_avatar,
            thumbnail=bot_avatar,
            fields=fields,
            footer="Use /help for the full command list",
            client=client,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
