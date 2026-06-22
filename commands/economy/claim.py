"""/claim — unified hub for daily reward, bounties, and investment status."""
from __future__ import annotations

import discord

from core.action_panel_views import claim_panel_view
from core.claim_panel import build_claim_hub
from core.refresh_panels import refresh_edit_message, register_refresh_panel
from core.utils import feature_off_embed, ECONOMY_ENABLED


async def refresh_claim_panel(interaction: discord.Interaction) -> bool:
    """Refresh handler for persistent claim hub panels."""
    if not interaction.guild:
        return False
    gid = interaction.guild.id
    uid = int(interaction.user.id)
    embed, payload, flags = await build_claim_hub(gid, uid, client=interaction.client)
    view = claim_panel_view(
        guild_id=gid,
        user_id=uid,
        daily_ready=flags["daily_ready"],
        bounty_ready=flags["bounty_ready"],
        invest_ready=flags["invest_ready"],
    )
    await refresh_edit_message(
        interaction,
        embed=embed,
        view=view,
        panel_type="claim_hub",
        payload=payload,
    )
    return True


def setup(bot, group=None):
    """Top-level /claim shortcut (economy group is near capacity)."""
    group = None

    @bot.tree.command(
        name="claim",
        description="See what's ready to claim — daily, bounties, and investments.",
    )
    async def claim(interaction: discord.Interaction):
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            from core.reply_helpers import reply_server_only
            return await reply_server_only(interaction)

        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        uid = interaction.user.id
        embed, payload, flags = await build_claim_hub(gid, uid, client=interaction.client)
        view = claim_panel_view(
            guild_id=gid,
            user_id=uid,
            daily_ready=flags["daily_ready"],
            bounty_ready=flags["bounty_ready"],
            invest_ready=flags["invest_ready"],
        )
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await register_refresh_panel(msg, "claim_hub", payload)
