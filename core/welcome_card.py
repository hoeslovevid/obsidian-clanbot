"""Public welcome channel card with quick-start buttons."""
from __future__ import annotations

import discord

from core.utils import obsidian_embed, EMBED_COLORS


class WelcomeCardView(discord.ui.View):
    """Pinned-style welcome actions for #welcome channel."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Set timezone", style=discord.ButtonStyle.primary, emoji="🌐", custom_id="welcome:tz")
    async def timezone_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🌐 Timezone",
                "Run **`/preferences`** and pick your timezone for reminders and event times.",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Set platform", style=discord.ButtonStyle.primary, emoji="🎮", custom_id="welcome:platform")
    async def platform_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🎮 Platform",
                "Run **`/preferences`** → **platform** (PC, Xbox, PlayStation, Switch).",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Open menu", style=discord.ButtonStyle.success, emoji="📋", custom_id="welcome:menu")
    async def menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=obsidian_embed(
                "📋 Quick menu",
                "Run **`/menu`** for daily, profile, Baro, LFG, tickets, and more.\n"
                "New here? Try **`/start`** or **`/help`**.",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            ),
            ephemeral=True,
        )


def welcome_card_embed(member: discord.Member, *, client=None) -> discord.Embed:
    return obsidian_embed(
        f"Welcome, {member.display_name}!",
        f"{member.mention} joined **{member.guild.name}**.\n\n"
        "Tap a button below to get started, or run **`/menu`** anytime.",
        color=EMBED_COLORS["success"],
        client=client,
    )
