"""Persistent routing for ``/warframe hub`` hint buttons (``wf_hub:*``)."""
from __future__ import annotations

import discord

from core.utils import obsidian_embed, EMBED_COLORS


async def handle_wf_hub_button(interaction: discord.Interaction, custom_id: str) -> bool:
    """Route hub panel buttons. Returns True if handled."""
    if not custom_id.startswith("wf_hub:"):
        return False

    action = custom_id.split(":", 1)[1]
    client = interaction.client

    if action == "baro_wish":
        if not interaction.guild:
            from core.reply_helpers import reply_server_only

            await reply_server_only(interaction)
            return True
        from commands.warframe.hub import BaroWishlistModal

        await interaction.response.send_modal(BaroWishlistModal(interaction.guild.id))
        return True

    if action == "status_hint":
        await interaction.response.send_message(
            "Run **`/warframe status`** for Baro, alerts, cycles, fissures, sortie, and invasions.",
            ephemeral=True,
        )
        return True

    if action == "notify_hint":
        await interaction.response.send_message(
            "Run **`/wfnotify configure`** — recommended wizard for Baro, cycles, and alerts.",
            ephemeral=True,
        )
        return True

    if action == "lfg_hint":
        await interaction.response.send_message(
            "Run **`/lfg`** to post a squad — or **`/lfg list`** to browse open posts.",
            ephemeral=True,
        )
        return True

    if action == "my_fissures":
        if not interaction.guild:
            from core.reply_helpers import reply_server_only

            await reply_server_only(interaction)
            return True
        from core.user_prefs import default_fissure_tier

        tier = await default_fissure_tier(interaction.guild.id, interaction.user.id)
        tier_note = f" (preset: **{tier}**)" if tier and tier != "all" else ""
        await interaction.response.send_message(
            f"Run **`/warframe fissures`** to see void fissures{tier_note}.\n"
            "-# Set a default tier in **`/preferences fissure_tier`**.",
            ephemeral=True,
        )
        return True

    await interaction.response.send_message(
        embed=obsidian_embed(
            "Warframe Hub",
            "Run **`/warframe hub`** for a fresh panel.",
            color=EMBED_COLORS["warframe"],
            client=client,
        ),
        ephemeral=True,
    )
    return True
