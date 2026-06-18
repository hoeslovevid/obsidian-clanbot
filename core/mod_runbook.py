"""Mod dashboard quick-runbook buttons (announce templates)."""
from __future__ import annotations

import discord

from core.utils import obsidian_embed, is_mod


class ModRunbookView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    async def _require_mod(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message(
                embed=obsidian_embed("Moderators only", "Staff use only.", client=interaction.client),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="WF API down", style=discord.ButtonStyle.secondary, emoji="🌐")
    async def wf_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        text = (
            "🌐 **Warframe data notice** — The public stats API is struggling. "
            "Bot commands may show cached data. We'll update when it's back.\n"
            "Use `/warframe status` or tap **Notify me when back** on any WF command."
        )
        await interaction.response.send_message(
            embed=obsidian_embed("📋 Announcement draft", text, client=interaction.client),
            ephemeral=True,
        )

    @discord.ui.button(label="Raid / lockdown", style=discord.ButtonStyle.danger, emoji="🛡️")
    async def raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        text = (
            "🛡️ **Server notice** — Staff are monitoring unusual activity. "
            "Please follow mod directions and avoid spam.\n"
            "Use `/mod incident` if you need to enable incident mode."
        )
        await interaction.response.send_message(
            embed=obsidian_embed("📋 Announcement draft", text, client=interaction.client),
            ephemeral=True,
        )

    @discord.ui.button(label="Economy pause", style=discord.ButtonStyle.secondary, emoji="💰")
    async def economy(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        text = (
            "💰 **Economy notice** — Coin rewards may be paused briefly while staff investigate an issue.\n"
            "Your balances are safe. Check `/whatsnew` for updates."
        )
        await interaction.response.send_message(
            embed=obsidian_embed("📋 Announcement draft", text, client=interaction.client),
            ephemeral=True,
        )

    @discord.ui.button(label="All clear", style=discord.ButtonStyle.success, emoji="✅")
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        text = (
            "✅ **All clear** — Systems are operating normally. Thanks for your patience."
        )
        await interaction.response.send_message(
            embed=obsidian_embed("📋 Announcement draft", text, client=interaction.client),
            ephemeral=True,
        )
