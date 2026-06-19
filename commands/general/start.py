"""Quick start guide for new members."""
from __future__ import annotations

import discord
from discord import app_commands

from core.embed_templates import embed_template
from core.reply_helpers import reply_server_only


def setup(bot, group=None):
    group = None

    @bot.tree.command(
        name="start",
        description="New here? Quick guide to daily, profile, Warframe tools, and support.",
    )
    async def start(interaction: discord.Interaction):
        if not interaction.guild:
            return await reply_server_only(interaction)
        embed = embed_template(
            "showcase",
            "👋 Welcome to Obsidian Bot",
            (
                "**3-step quick start**\n"
                "1. `/daily` — claim coins · 2. `/profile` — your stats · 3. `/baro` or `/lfg`\n\n"
                "**Explore**\n"
                "• `/menu` — shortcuts · `/search` — find commands · `/preferences` — timezone & quiet hours\n"
                "• `/wfnotify configure` — Warframe alert DMs · `/ticket` — staff help\n\n"
                "**Need humans?** `/feedback` for bot issues · `/ticket` for server support"
            ),
            category="community",
            footer="Pin this in #rules or #welcome for new members",
            client=interaction.client,
            brand=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
