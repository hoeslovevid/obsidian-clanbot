"""Pinned world-state board and worth-now summary for Warframe."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands

from api.warframe_api import (
    fetch_fissures,
    fetch_invasions,
    get_all_cycles,
    get_baro_status,
    wf_staleness_for_path,
)
from commands.warframe.status import (
    _format_baro_summary,
    _format_cycles_summary,
    _format_invasions_summary,
)
from core.embed_templates import embed_template
from core.utils import (
    BUTTON_ONLY_RUNNER_MSG,
    error_embed,
    is_mod,
    success_embed,
    warframe_data_unavailable_embed,
)
from database import get_guild_setting, set_guild_setting
from views import RefreshView

logger = logging.getLogger(__name__)

_FISSURE_TIER_RANK = {"Requiem": 5, "Axi": 4, "Neo": 3, "Meso": 2, "Lith": 1}


def _world_state_msg_key(channel_id: int) -> str:
    return f"world_state_msg:{channel_id}"


def _world_state_cached_at() -> Optional[datetime]:
    """Use the oldest relevant cache stamp for the board footer."""
    stamps = [
        wf_staleness_for_path("pc/voidTrader"),
        wf_staleness_for_path("pc/cetusCycle"),
    ]
    valid = [t for t in stamps if t is not None]
    return min(valid) if valid else None


async def build_world_state_embed(client) -> discord.Embed:
    """Baro line + open-world cycles for the pinned board."""
    is_active, baro_data = await get_baro_status()
    cycles_data = await get_all_cycles() or {}

    fields = []
    if baro_data:
        title, value = _format_baro_summary(baro_data, is_active)
        fields.append((title, value, False))
    else:
        fields.append(("🛒 Baro Ki'Teer", "Unable to fetch", False))

    fields.append(("🌍 Open World Cycles", _format_cycles_summary(cycles_data), False))

    now_ts = int(datetime.now(timezone.utc).timestamp())
    return embed_template(
        "warframe_status",
        "🌍 Warframe World State",
        f"> Live snapshot • updated <t:{now_ts}:R>",
        variant="world_state",
        platform="pc",
        client=client,
        cached_at=_world_state_cached_at(),
        fields=fields,
        footer="Pinned board · Use **Update data** to refresh · /warframe worth",
    )


def _best_fissure_hint(fissures: list) -> str:
    """Pick a single high-value fissure line for the worth embed."""
    active = [f for f in fissures if not f.get("expired", False)]
    if not active:
        return "No active fissures"

    def score(f: dict) -> tuple:
        tier = f.get("tier") or ""
        return (
            1 if f.get("isHard") else 0,
            _FISSURE_TIER_RANK.get(tier, 0),
        )

    best = max(active, key=score)
    tier = best.get("tier", "?")
    node = best.get("node", "?")
    mission = best.get("missionType", "?")
    sp = " · Steel Path" if best.get("isHard") else ""
    storm = " · Void Storm" if best.get("isStorm") else ""
    return f"**{tier}** {node} — {mission}{sp}{storm}"


async def build_worth_embed(client) -> discord.Embed:
    """Aggregate best fissure, invasion, and cycle picks."""
    fissures, invasions, cycles = await asyncio.gather(
        fetch_fissures(),
        fetch_invasions(),
        get_all_cycles(),
    )
    cycles = cycles or {}
    fissures = fissures or []
    invasions = invasions or []

    fields = [
        ("⚡ Best fissure", _best_fissure_hint(fissures), False),
        ("⚔️ Invasions", _format_invasions_summary(invasions), False),
        ("🌍 Cycles", _format_cycles_summary(cycles), False),
    ]

    cached = _world_state_cached_at()
    if wf_staleness_for_path("pc/fissures"):
        cached = wf_staleness_for_path("pc/fissures")

    return embed_template(
        "warframe_status",
        "✨ What's Worth Doing Now",
        "> Quick picks from live world state (PC)",
        variant="fissures",
        platform="pc",
        client=client,
        cached_at=cached,
        fields=fields,
        footer="Use **Update data** to refresh · /warframe world_state for pinned board",
    )


def setup(bot, group=None):
    """Register world_state and worth subcommands."""
    if not group:
        return

    @group.command(
        name="world_state",
        description="Post or refresh a pinned world-state board (mods only).",
    )
    @app_commands.describe(
        channel="Channel for the board (defaults to current channel).",
    )
    async def world_state(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed(
                    "Permission Denied",
                    "Only moderators can post the world-state board.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Channel", "Pick a text channel.", client=interaction.client),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        is_active, baro_data = await get_baro_status()
        cycles_data = await get_all_cycles() or {}
        if not baro_data and not any(cycles_data.values()):
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                ephemeral=True,
            )

        embed = await build_world_state_embed(interaction.client)

        msg_key = _world_state_msg_key(target.id)
        stored_id = await get_guild_setting(interaction.guild.id, msg_key)
        message: Optional[discord.Message] = None

        if stored_id and stored_id.isdigit():
            try:
                message = await target.fetch_message(int(stored_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None

        async def on_refresh(btn_interaction: discord.Interaction):
            from core.cache_utils import invalidate

            invalidate("warframe:baro")
            invalidate("warframe:cycles")
            new_emb = await build_world_state_embed(interaction.client)
            view = RefreshView(on_refresh, timeout=None)
            try:
                await btn_interaction.message.edit(embed=new_emb, view=view)
            except discord.HTTPException as e:
                logger.debug("[world_state] refresh edit failed: %s", e)

        view = RefreshView(on_refresh, timeout=None)

        try:
            if message:
                await message.edit(embed=embed, view=view)
            else:
                message = await target.send(embed=embed, view=view)
                await set_guild_setting(interaction.guild.id, msg_key, str(message.id))
            try:
                await message.pin()
            except discord.HTTPException:
                pass
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=error_embed(
                    "Missing Permission",
                    f"I can't send or edit messages in {target.mention}.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        action = "refreshed" if stored_id else "posted"
        await interaction.followup.send(
            embed=success_embed(
                "World State Board",
                f"Board {action} in {target.mention}.",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @group.command(
        name="worth",
        description="What's worth doing now — fissures, invasions, cycles.",
    )
    async def worth(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        embed = await build_worth_embed(interaction.client)
        fissures, invasions, cycles = await asyncio.gather(
            fetch_fissures(), fetch_invasions(), get_all_cycles(),
        )
        if not fissures and not invasions and not any((cycles or {}).values()):
            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                new_emb = await build_worth_embed(interaction.client)
                await btn_interaction.message.edit(embed=new_emb, view=None)

            from views import RetryView

            from core.wf_recovery import attach_notify_when_back
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=attach_notify_when_back(RetryView(on_retry)),
                ephemeral=True,
            )

        async def on_refresh(btn_interaction: discord.Interaction):
            # Read-only public data — anyone may refresh.
            from core.cache_utils import invalidate

            invalidate("warframe:fissures")
            invalidate("warframe:invasions")
            invalidate("warframe:cycles")
            new_emb = await build_worth_embed(interaction.client)
            view = RefreshView(on_refresh)
            await btn_interaction.message.edit(embed=new_emb, view=view)

        view = RefreshView(on_refresh)
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)
