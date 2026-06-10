"""Pinned live open-world cycles panel — `/wfnotify cycle_panel`."""
from __future__ import annotations

import logging
from typing import Optional

import discord  # type: ignore
from discord import app_commands

from api.warframe_api import get_all_cycles
from core.cycles_live import (
    build_cycles_live_embed,
    get_cycle_live_message_id,
    register_cycle_live_message,
)
from core.utils import error_embed, is_mod, success_embed, warframe_data_unavailable_embed
from views import RefreshView

logger = logging.getLogger(__name__)


def setup(bot, group=None):
    """Register `/wfnotify cycle_panel` (mods only)."""
    cmd = (
        group.command(
            name="cycle_panel",
            description="Post or refresh a pinned live cycles board (mods only).",
        )
        if group
        else None
    )
    if not cmd:
        return

    @cmd
    @app_commands.describe(
        channel="Channel for the live panel (defaults to current channel).",
    )
    async def cycle_panel(
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
                    "Only moderators can post the cycles live panel.",
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

        cycles_data = await get_all_cycles()
        success = {k: v for k, v in (cycles_data or {}).items() if v}
        if not success:
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                ephemeral=True,
            )

        embed = build_cycles_live_embed(interaction.client, cycles_data or {})
        stored_id = await get_cycle_live_message_id(interaction.guild.id, target.id)
        message: Optional[discord.Message] = None

        if stored_id:
            try:
                message = await target.fetch_message(stored_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None

        async def on_refresh(btn_interaction: discord.Interaction):
            from core.cache_utils import invalidate

            invalidate("warframe:cycles")
            fresh = await get_all_cycles()
            if not any(v for v in (fresh or {}).values()):
                return
            new_emb = build_cycles_live_embed(interaction.client, fresh or {})
            view = RefreshView(on_refresh, timeout=None)
            try:
                await btn_interaction.message.edit(embed=new_emb, view=view)
            except discord.HTTPException as exc:
                logger.debug("[cycle_panel] refresh edit failed: %s", exc)

        view = RefreshView(on_refresh, timeout=None)

        try:
            if message:
                await message.edit(embed=embed, view=view)
            else:
                message = await target.send(embed=embed, view=view)
            try:
                await message.pin()
            except discord.HTTPException:
                pass
            await register_cycle_live_message(
                interaction.guild.id,
                target.id,
                message.id,
            )
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
        hint = (
            "Cycle flip pings are disabled while this panel is active — "
            "the board updates in place every few minutes."
        )
        await interaction.followup.send(
            embed=success_embed(
                "Cycles Live Panel",
                f"Panel {action} in {target.mention}.\n\n{hint}",
                client=interaction.client,
            ),
            ephemeral=True,
        )
