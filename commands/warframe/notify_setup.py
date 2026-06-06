"""Unified `/wfnotify setup` panel (Item 3).

Lets a mod set or clear every Warframe notification channel from a single
ephemeral embed. Persists into the same setting keys/tables the individual
``*_notify`` commands already use, so existing notification senders pick up
the changes immediately.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord
from discord import app_commands
import aiosqlite  # type: ignore

from core.utils import obsidian_embed, success_embed, error_embed, is_mod
from database import DB_PATH, get_guild_setting, set_guild_setting


# ---------------------------------------------------------------------------
# Per-category storage adapters
# ---------------------------------------------------------------------------
# Each entry: (slug, label, getter, setter)
#   getter(guild_id) -> Optional[int]  # current channel id, None if unset
#   setter(guild_id, channel_id|None)  # None clears
# Cycles enables all three open-world cycles for the chosen channel.
# Invasions/warframe-event are intentionally omitted because they have richer
# per-reward / toggle semantics — point users to those commands for fine grain.


async def _get_baro(guild_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id, enabled FROM baro_notification_settings WHERE guild_id=?",
            (guild_id,),
        )
        row = await cur.fetchone()
    if row and row[1] and row[0]:
        return int(row[0])
    return None


async def _set_baro(guild_id: int, channel_id: Optional[int]) -> None:
    enabled = 1 if channel_id else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO baro_notification_settings (guild_id, channel_id, enabled)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                enabled    = excluded.enabled
            """,
            (guild_id, channel_id or 0, enabled),
        )
        await db.commit()


async def _get_archon(guild_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id, enabled FROM archon_notification_settings WHERE guild_id=?",
            (guild_id,),
        )
        row = await cur.fetchone()
    if row and row[1] and row[0]:
        return int(row[0])
    return None


async def _set_archon(guild_id: int, channel_id: Optional[int]) -> None:
    enabled = 1 if channel_id else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO archon_notification_settings (guild_id, channel_id, enabled)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                enabled    = excluded.enabled
            """,
            (guild_id, channel_id or 0, enabled),
        )
        await db.commit()


async def _get_cycles(guild_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id, cetus_enabled, fortuna_enabled, deimos_enabled "
            "FROM cycle_notification_settings WHERE guild_id=?",
            (guild_id,),
        )
        row = await cur.fetchone()
    if row and row[0] and (row[1] or row[2] or row[3]):
        return int(row[0])
    return None


async def _set_cycles(guild_id: int, channel_id: Optional[int]) -> None:
    on = 1 if channel_id else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO cycle_notification_settings
                (guild_id, channel_id, cetus_enabled, fortuna_enabled, deimos_enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id      = excluded.channel_id,
                cetus_enabled   = excluded.cetus_enabled,
                fortuna_enabled = excluded.fortuna_enabled,
                deimos_enabled  = excluded.deimos_enabled
            """,
            (guild_id, channel_id or 0, on, on, on),
        )
        await db.commit()


def _make_setting_getter(key: str) -> Callable[[int], Awaitable[Optional[int]]]:
    async def _getter(guild_id: int) -> Optional[int]:
        raw = await get_guild_setting(guild_id, key)
        if raw and str(raw).isdigit():
            return int(raw)
        return None
    return _getter


def _make_setting_setter(key: str) -> Callable[[int, Optional[int]], Awaitable[None]]:
    async def _setter(guild_id: int, channel_id: Optional[int]) -> None:
        await set_guild_setting(guild_id, key, str(channel_id) if channel_id else "")
    return _setter


# Slug → (label, getter, setter)
NOTIFY_CATEGORIES: dict[str, tuple[str, Callable, Callable]] = {
    "baro":      ("🛒 Baro Ki'Teer",     _get_baro, _set_baro),
    "cycles":    ("🌍 Open-world Cycles", _get_cycles, _set_cycles),
    "archon":    ("👹 Archon Hunt",       _get_archon, _set_archon),
    "alerts":    ("🚨 Alerts",
                  _make_setting_getter("alerts_notify_channel_id"),
                  _make_setting_setter("alerts_notify_channel_id")),
    "devstream": ("📺 Devstream",
                  _make_setting_getter("devstream_notify_channel_id"),
                  _make_setting_setter("devstream_notify_channel_id")),
    "forum":     ("📰 DE Forum",
                  _make_setting_getter("forum_notify_channel_id"),
                  _make_setting_setter("forum_notify_channel_id")),
    "youtube":   ("🎥 YouTube",
                  _make_setting_getter("youtube_notify_channel_id"),
                  _make_setting_setter("youtube_notify_channel_id")),
    "tennogen":  ("🎨 TennoGen",
                  _make_setting_getter("tennogen_notify_channel_id"),
                  _make_setting_setter("tennogen_notify_channel_id")),
}


def _fmt_channel(guild: discord.Guild, channel_id: Optional[int]) -> str:
    if not channel_id:
        return "_unset_"
    ch = guild.get_channel(int(channel_id))
    return ch.mention if ch else f"<#{channel_id}> _(missing)_"


async def _build_overview_embed(
    interaction: discord.Interaction,
    flash: Optional[str] = None,
) -> discord.Embed:
    """Build the panel embed listing each category and its current channel."""
    guild = interaction.guild
    lines: list[str] = []
    for slug, (label, getter, _setter) in NOTIFY_CATEGORIES.items():
        try:
            ch_id = await getter(guild.id)
        except Exception:
            ch_id = None
        lines.append(f"**{label}** — {_fmt_channel(guild, ch_id)}")

    # Mention the categories we intentionally don't manage from here so mods
    # know to use their dedicated commands.
    extras = (
        "\n\n_For per-reward invasion pings, use `/wfnotify invasion_notify`._\n"
        "_For automatic event creation toggle, use `/wfnotify warframe_event_notify`._\n"
        "_For open-world cycles, post a live panel with `/wfnotify cycle_panel` instead of flip pings._"
    )

    desc = "Use the menu to set or clear a channel for each notification stream.\n\n" + "\n".join(lines) + extras
    return obsidian_embed(
        "📡 Warframe Notify Setup",
        desc + (f"\n\n_{flash}_" if flash else ""),
        category="warframe",
        client=interaction.client,
        footer="Per-user opt-in pings: /warframe subscribe",
    )


class _ChannelPickerView(discord.ui.View):
    """Stage 2 — after a category is chosen, prompt for a channel."""

    def __init__(self, parent: "NotifySetupView", slug: str):
        super().__init__(timeout=180)
        self.parent = parent
        self.slug = slug
        label, _g, _s = NOTIFY_CATEGORIES[slug]
        self.label = label

        select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            placeholder=f"Pick a channel for {label} (or skip → Clear)",
            min_values=0,
            max_values=1,
            custom_id=f"wf_notify_setup_chan:{slug}",
        )
        select.callback = self._on_channel  # type: ignore[assignment]
        self.add_item(select)

        clear_btn = discord.ui.Button(
            label="Clear / Disable",
            style=discord.ButtonStyle.danger,
            emoji="🗑️",
        )
        clear_btn.callback = self._on_clear  # type: ignore[assignment]
        self.add_item(clear_btn)

        back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._on_back  # type: ignore[assignment]
        self.add_item(back_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.parent.invoker_id

    async def _on_channel(self, interaction: discord.Interaction):
        select: discord.ui.ChannelSelect = self.children[0]  # type: ignore[assignment]
        values = list(select.values)
        if not values:
            return await self._on_clear(interaction)
        channel = values[0]
        _label, getter, setter = NOTIFY_CATEGORIES[self.slug]
        prev = await getter(interaction.guild.id)
        await setter(interaction.guild.id, int(channel.id))
        flash = (
            f"✅ **{self.label}**: {_fmt_channel(interaction.guild, prev)} → <#{channel.id}>"
        )
        if self.slug == "cycles":
            flash += "\n_Post a live panel with `/wfnotify cycle_panel` to replace flip pings._"
        await self.parent.return_to_overview(interaction, flash=flash)

    async def _on_clear(self, interaction: discord.Interaction):
        _label, getter, setter = NOTIFY_CATEGORIES[self.slug]
        prev = await getter(interaction.guild.id)
        await setter(interaction.guild.id, None)
        flash = f"🗑️ **{self.label}**: {_fmt_channel(interaction.guild, prev)} → _unset_"
        await self.parent.return_to_overview(interaction, flash=flash)

    async def _on_back(self, interaction: discord.Interaction):
        await self.parent.return_to_overview(interaction)


class NotifySetupView(discord.ui.View):
    """Top-level view: select category, then drill into channel picker."""

    def __init__(self, invoker_id: int):
        super().__init__(timeout=300)
        self.invoker_id = invoker_id

        options = [
            discord.SelectOption(label=label.split(" ", 1)[-1], value=slug, emoji=label.split(" ", 1)[0])
            for slug, (label, _g, _s) in NOTIFY_CATEGORIES.items()
        ]
        select = discord.ui.Select(
            placeholder="Pick a notification stream to configure…",
            options=options,
            custom_id="wf_notify_setup_pick",
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_pick  # type: ignore[assignment]
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.invoker_id

    async def _on_pick(self, interaction: discord.Interaction):
        select: discord.ui.Select = self.children[0]  # type: ignore[assignment]
        slug = select.values[0]
        picker = _ChannelPickerView(self, slug)
        await interaction.response.edit_message(
            embed=await _build_overview_embed(interaction, flash=f"Configuring **{NOTIFY_CATEGORIES[slug][0]}**…"),
            view=picker,
        )

    async def return_to_overview(self, interaction: discord.Interaction, *, flash: Optional[str] = None):
        await interaction.response.edit_message(
            embed=await _build_overview_embed(interaction, flash=flash),
            view=self,
        )


def setup(bot, group=None):
    """Register the `/wfnotify setup` command."""
    cmd = group.command(name="setup", description="Configure every Warframe notification channel from one panel.") if group else None
    if not cmd:
        return

    @cmd
    async def notify_setup(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed(
                    "Permission Denied",
                    "Only administrators can configure notification channels.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        view = NotifySetupView(interaction.user.id)
        embed = await _build_overview_embed(interaction)
        from core.help_layout import help_layout_v2_enabled
        from core.wfnotify_layout import WfNotifyConfigureLayout

        if help_layout_v2_enabled():
            try:
                overview = embed.description or "Configure Warframe notification channels."
                cats = [(slug, label) for slug, (label, _g, _s) in NOTIFY_CATEGORIES.items()]

                async def _on_pick(inter: discord.Interaction, slug: str):
                    picker = _ChannelPickerView(view, slug)
                    await inter.response.edit_message(
                        embed=await _build_overview_embed(inter, flash=f"Configuring **{NOTIFY_CATEGORIES[slug][0]}**…"),
                        view=picker,
                    )

                layout = WfNotifyConfigureLayout(
                    overview_text=overview,
                    on_pick=_on_pick,
                    categories=cats,
                )
                msg = await interaction.followup.send(view=layout, ephemeral=True)
                try:
                    view.message = msg  # type: ignore[attr-defined]
                except Exception:
                    pass
                return
            except Exception:
                pass
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        try:
            view.message = msg  # type: ignore[attr-defined]
        except Exception:
            pass
