"""Quick start guide for new members."""
from __future__ import annotations

import discord
from discord import app_commands

from core.embed_templates import embed_template
from core.command_surface import discovery_12_block
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
                "**Discovery 12 — your starter commands:**\n\n"
                + discovery_12_block()
                + "\n\n**Tip:** `/menu` for shortcuts · `/search` for anything else · "
                "`/preferences` for timezone & quiet hours\n\n"
                "**Need humans?** `/feedback` for bot issues · `/ticket` for server support"
            ),
            category="community",
            footer="Pin this in #rules or #welcome for new members",
            client=interaction.client,
            brand=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
