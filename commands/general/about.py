"""About command - bot description, features, and developer info."""
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.embed_templates import embed_template
from core.changelog import get_latest_changelog_entry
from core.config import BOT_WEBSITE, BOT_DEVELOPER, BOT_CHANGELOG
from core.version_tracking import get_current_bot_version


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

        version = await get_current_bot_version()
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

        whats_new = ""
        try:
            entry = get_latest_changelog_entry()
            bullets = entry.get("changes") or []
            if bullets:
                whats_new = "\n".join(f"• {c}" for c in bullets[:4])
                if len(bullets) > 4:
                    whats_new += f"\n• _+{len(bullets) - 4} more — `/whatsnew`_"
        except Exception:
            pass
        if not whats_new and BOT_CHANGELOG.strip():
            whats_new = BOT_CHANGELOG.strip()[:900]

        fields = [
            ("📋 Main Features", features, False),
            ("📌 Version", version, True),
        ]
        if whats_new:
            fields.insert(1, ("✨ What's New", whats_new, False))
        if BOT_DEVELOPER:
            fields.append(("👤 Developer", BOT_DEVELOPER, True))
        if BOT_WEBSITE:
            fields.append(("🌐 Website", f"[Visit]({BOT_WEBSITE})", True))

        embed = embed_template(
            "showcase",
            f"About {bot_name}",
            f"> {desc}",
            category="general",
            author_name=bot_name,
            author_icon=bot_avatar,
            thumbnail=bot_avatar,
            fields=fields,
            footer="Use /help for the full command list",
            client=client,
            brand=True,
        )

        from core.compact_layouts import AboutLayout
        from core.help_layout import help_layout_v2_enabled

        if help_layout_v2_enabled():
            try:
                layout = AboutLayout(
                    title=f"About {bot_name}",
                    intro=desc,
                    fields=[(n, v, inl) for n, v, inl in fields],
                )
                await interaction.response.send_message(view=layout, ephemeral=True)
                return
            except Exception:
                pass

        await interaction.response.send_message(embed=embed, ephemeral=True)
