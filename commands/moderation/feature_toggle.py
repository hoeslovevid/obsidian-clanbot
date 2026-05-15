"""Item 85 — per-guild feature kill switch.

Adds:
- ``/admin features list``  — show current per-feature on/off state
- ``/admin features toggle`` — flip a single feature, with a confirm modal
  ("are you sure" prompt because turning a feature off affects everyone)

Storage uses the existing ``guild_settings`` rows: ``feature:{name} = "off"``
when disabled (absence means enabled). The runtime check lives in
``core.utils.feature_enabled()``.
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands

from core.utils import (
    EMBED_COLORS,
    TOGGLEABLE_FEATURES,
    error_embed,
    is_mod,
    obsidian_embed,
    success_embed,
)
from database import get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)


class _ConfirmDisableModal(discord.ui.Modal, title="Confirm feature toggle"):
    confirmation = discord.ui.TextInput(
        label="Type CONFIRM to apply this change",
        placeholder="CONFIRM",
        required=True,
        min_length=2,
        max_length=20,
    )

    def __init__(self, feature: str, new_state: str, on_done):
        super().__init__()
        self.feature = feature
        self.new_state = new_state
        self.on_done = on_done

    async def on_submit(self, interaction: discord.Interaction):
        if str(self.confirmation.value).strip().upper() != "CONFIRM":
            return await interaction.response.send_message(
                embed=error_embed(
                    "Cancelled",
                    "You didn't type `CONFIRM` exactly — feature toggle aborted.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await self.on_done(interaction)


def setup(bot, group=None):
    """Register `/<group> features` (admin-only). When `group` is `None`
    we fall back to a top-level ``/features`` group."""
    target = group if group is not None else bot.tree
    features_group = app_commands.Group(name="features", description="🔒 (admin) Per-feature kill switch.")

    @features_group.command(name="list", description="(mods) Show on/off state of every togglable feature.")
    async def features_list(interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Only administrators can view feature toggles.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        lines: list[str] = []
        for feat in TOGGLEABLE_FEATURES:
            val = await get_guild_setting(interaction.guild.id, f"feature:{feat}")
            on = val != "off"
            lines.append(f"{'🟢' if on else '🔴'} **{feat}** — {'on' if on else 'OFF'}")
        await interaction.followup.send(
            embed=obsidian_embed(
                "🔒 Feature Toggles",
                "\n".join(lines) +
                "\n\nUse `/admin features toggle feature:<name> state:on|off` to flip a feature.",
                color=EMBED_COLORS["moderation"],
                client=interaction.client,
                footer="Per-guild · overrides bot-wide env flags.",
            ),
            ephemeral=True,
        )

    @features_group.command(name="toggle", description="(mods) Turn a feature on or off for this server (with confirm).")
    @app_commands.choices(
        feature=[app_commands.Choice(name=f, value=f) for f in TOGGLEABLE_FEATURES],
        state=[
            app_commands.Choice(name="On", value="on"),
            app_commands.Choice(name="Off", value="off"),
        ],
    )
    async def features_toggle(
        interaction: discord.Interaction,
        feature: app_commands.Choice[str],
        state: app_commands.Choice[str],
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Only administrators can toggle features.", client=interaction.client),
                ephemeral=True,
            )

        feat = feature.value
        new_state = state.value

        async def _apply(modal_inter: discord.Interaction):
            try:
                if new_state == "off":
                    await set_guild_setting(modal_inter.guild.id, f"feature:{feat}", "off")
                else:
                    await set_guild_setting(modal_inter.guild.id, f"feature:{feat}", "")
            except Exception as e:
                return await modal_inter.response.send_message(
                    embed=error_embed("Couldn't update", str(e), client=modal_inter.client),
                    ephemeral=True,
                )
            await modal_inter.response.send_message(
                embed=success_embed(
                    "Feature Updated",
                    f"**{feat}** is now **{'ON' if new_state == 'on' else 'OFF'}** for this server.",
                    client=modal_inter.client,
                ),
                ephemeral=True,
            )

        await interaction.response.send_modal(_ConfirmDisableModal(feat, new_state, _apply))

    if isinstance(target, app_commands.Group):
        target.add_command(features_group)
    else:
        bot.tree.add_command(features_group)
