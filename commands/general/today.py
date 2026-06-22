"""Top-level /today — unified daily priorities panel."""
from __future__ import annotations

import discord

from core.action_panel_views import today_panel_view
from core.embed_prefs import embed_kwargs
from core.progress_nudge import append_progress_nudge
from core.refresh_panels import refresh_edit_message, register_refresh_panel
from core.reply_helpers import reply_server_only
from core.today_panel import build_today_fields, gather_today_data, today_footer
from core.utils import ECONOMY_ENABLED, EMBED_COLORS, feature_off_embed, obsidian_embed


async def build_today_embed(
    guild: discord.Guild,
    user: discord.abc.User,
    *,
    client=None,
) -> tuple[discord.Embed, discord.ui.View, dict]:
    """Build today embed, action view, and refresh payload."""
    data = await gather_today_data(guild.id, user.id, bot=client)
    fields = build_today_fields(data)
    footer = today_footer(data)
    body = f"Here's what matters today in **{guild.name}**."
    body = await append_progress_nudge(body, guild.id, user.id, context="general")

    embed = obsidian_embed(
        f"📅 Today · {user.display_name}",
        body,
        color=EMBED_COLORS["general"],
        template="profile",
        category="general",
        fields=fields,
        footer=footer,
        client=client,
        **(await embed_kwargs(guild.id, user.id)),
    )
    show_baro = bool(data["baro_active"] and data["baro_wishlist_hits"])
    view = today_panel_view(
        guild_id=guild.id,
        user_id=user.id,
        show_daily=not data["daily_claimed"],
        show_baro=bool(data["baro_active"]),
    )
    payload = {"guild_id": guild.id, "user_id": user.id}
    return embed, view, payload


async def refresh_today_panel(interaction: discord.Interaction) -> bool:
    """Refresh handler for persistent today panels."""
    if not interaction.guild:
        return False
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    embed, view, payload = await build_today_embed(
        interaction.guild,
        interaction.user,
        client=interaction.client,
    )
    await refresh_edit_message(
        interaction,
        embed=embed,
        view=view,
        panel_type="today",
        payload=payload,
    )
    return True


async def _run_today(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        return await reply_server_only(interaction)
    if not ECONOMY_ENABLED:
        return await interaction.response.send_message(
            embed=feature_off_embed("Economy", client=interaction.client),
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)
    embed, view, payload = await build_today_embed(
        interaction.guild,
        interaction.user,
        client=interaction.client,
    )
    msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    await register_refresh_panel(msg, "today", payload)


def setup(bot, group=None):
    """Register /today top-level shortcut."""

    @bot.tree.command(
        name="today",
        description="Your day at a glance — daily, bounties, Baro, LFG, events, and more.",
    )
    async def today_cmd(interaction: discord.Interaction):
        await _run_today(interaction)
