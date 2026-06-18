"""Persistent unwatch button on price-watch DM notifications."""
from __future__ import annotations

import discord
from discord import ui


class PriceWatchUnwatchView(ui.View):
    def __init__(self, guild_id: int, user_id: int, item_name: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.user_id = user_id
        self.item_name = item_name

    @ui.button(label="Stop watching", style=discord.ButtonStyle.secondary, emoji="🔕")
    async def unwatch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This watch belongs to someone else.", ephemeral=True)
        from core.price_watchlist import remove_watch

        ok, msg = await remove_watch(self.guild_id, self.user_id, self.item_name)
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content=f"🔕 {msg}",
            embed=None,
            view=self,
        )
