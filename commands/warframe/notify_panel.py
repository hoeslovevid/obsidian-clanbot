"""Persistent self-subscribe panel for Warframe notifications (Item 21).

Mods run ``/wfnotify post_panel`` to drop a single embed in a channel.
Each button on that embed toggles the user's
``wfsub:{category}:{user_id}`` setting — the same key shared by
``/warframe subscribe`` (Item 2) — so the two surfaces stay in sync.

The view uses static custom_ids and ``timeout=None`` so it survives restarts;
:func:`handlers.startup.register_persistent_views` registers an instance at
startup unconditionally.
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands

from core.utils import (
    obsidian_embed,
    success_embed,
    error_embed,
    is_mod,
    WF_SUB_CATEGORIES,
)
from database import get_guild_setting, set_guild_setting, delete_guild_setting

logger = logging.getLogger(__name__)


_CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "baro":      ("Baro",       "🛒"),
    "cycles":    ("Cycles",     "🌍"),
    "archon":    ("Archon",     "👹"),
    "alerts":    ("Alerts",     "🚨"),
    "invasions": ("Invasions",  "⚔️"),
    "devstream": ("Devstream",  "📺"),
}


def _label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, (category.title(), "🔔"))[0]


def _emoji(category: str) -> str:
    return _CATEGORY_LABELS.get(category, (category.title(), "🔔"))[1]


class NotifyPanelView(discord.ui.View):
    """Persistent view: one toggle button per WF_SUB_CATEGORIES entry.

    Custom IDs are static (``wfsub_toggle:{category}``) so registering a
    single instance at startup is enough to route every button back here.
    """

    def __init__(self):
        super().__init__(timeout=None)
        for cat in WF_SUB_CATEGORIES:
            if cat not in _CATEGORY_LABELS:
                continue
            btn = discord.ui.Button(
                label=_label(cat),
                style=discord.ButtonStyle.primary,
                emoji=_emoji(cat),
                custom_id=f"wfsub_toggle:{cat}",
            )
            btn.callback = self._make_callback(cat)
            self.add_item(btn)

    def _make_callback(self, category: str):
        async def _cb(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message(
                    "This panel only works in a server.", ephemeral=True
                )
            key = f"wfsub:{category}:{interaction.user.id}"
            current = await get_guild_setting(interaction.guild.id, key)
            label = _label(category)
            if current == "1":
                await delete_guild_setting(interaction.guild.id, key)
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        f"🔕 Unsubscribed from {label}",
                        f"You will no longer be pinged when **{label}** drops.\n\n"
                        f"Tap **{_emoji(category)} {label}** again to re-subscribe.",
                        category="warning",
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            await set_guild_setting(interaction.guild.id, key, "1")
            await interaction.response.send_message(
                embed=success_embed(
                    f"Subscribed to {label}",
                    f"You'll be pinged the next time **{label}** drops.\n\n"
                    f"Tap **{_emoji(category)} {label}** again to unsubscribe.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        return _cb


def build_panel_embed(client: Optional[discord.Client] = None) -> discord.Embed:
    """Build the public panel embed (also used at panel creation time)."""
    lines = ["Tap a button below to toggle pings for each Warframe stream.\n"]
    for cat in WF_SUB_CATEGORIES:
        if cat in _CATEGORY_LABELS:
            lines.append(f"{_emoji(cat)} **{_label(cat)}**")
    return obsidian_embed(
        "🔔 Warframe Notification Subscriptions",
        "\n".join(lines)
        + "\n\n_Only you see your subscription status. Use `/warframe subscribe` to view or change subscriptions outside this panel._",
        category="warframe",
        client=client,
        footer="Subscriptions are per-server and persist across restarts.",
    )


def setup(bot, group=None):
    """Register the panel poster command + the persistent view."""
    # Register the persistent view immediately so existing panels keep working.
    try:
        bot.add_view(NotifyPanelView())
    except Exception as e:
        logger.debug(f"[notify_panel] add_view failed (already registered?): {e}")

    cmd = group.command(name="post_panel", description="Post a persistent self-subscribe panel for Warframe pings (mods only).") if group else None
    if not cmd:
        return

    @cmd
    @app_commands.describe(channel="Channel to post the panel in (defaults to current channel).")
    async def post_panel(
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
                    "Only administrators can post the subscribe panel.",
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
        try:
            msg = await target.send(embed=build_panel_embed(interaction.client), view=NotifyPanelView())
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=error_embed(
                    "Missing Permission",
                    f"I can't send messages in {target.mention}. Grant **Send Messages** and try again.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # Track the panel so a future maintenance command could re-post it.
        await set_guild_setting(
            interaction.guild.id,
            "wfsub_panel_message",
            f"{target.id}:{msg.id}",
        )
        await interaction.followup.send(
            embed=success_embed(
                "Notify Panel Posted",
                f"Panel posted in {target.mention}. Buttons survive restarts.",
                client=interaction.client,
            ),
            ephemeral=True,
        )
