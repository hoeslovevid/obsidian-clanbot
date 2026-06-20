"""Action buttons on Baro wishlist match DMs."""
from __future__ import annotations

import discord
from discord import ui


class BaroWishlistDMView(ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @ui.button(label="Baro hub", style=discord.ButtonStyle.primary, emoji="🛒", custom_id="qol:baro_hub")
    async def hub(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Run **`/warframe hub`** or **`/baro`** in your server for the full Baro board.",
            ephemeral=True,
        )

    @ui.button(label="Post Baro LFG", style=discord.ButtonStyle.secondary, emoji="🤝", custom_id="qol:baro_lfg")
    async def lfg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Run **`/lfg`** with mission **Other** and note Baro farming in the description.",
            ephemeral=True,
        )
