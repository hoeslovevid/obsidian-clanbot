"""Refreshable Warframe hub — status snippet, Baro, notify, and LFG links."""
from __future__ import annotations

import asyncio

import discord  # type: ignore
from api.warframe_api import (
    fetch_alerts,
    fetch_arbitration,
    fetch_fissures,
    fetch_invasions,
    fetch_nightwave,
    fetch_sortie,
    fetch_steel_path,
    get_all_cycles,
    get_baro_status,
)
from commands.warframe.status import (
    _format_baro_summary,
    _format_cycles_summary,
    _format_fissures_summary,
)
from core.embed_footers import footer_for
from core.embed_links import add_link_row, baro_link_buttons, link_button
from core.embed_templates import embed_template
from core.utils import BUTTON_ONLY_RUNNER_MSG, warframe_data_unavailable_embed
from core.warframe_platform import resolve_warframe_platform, warframe_footer_platform_note
from core.music_player import format_guild_music_line
from core.wf_hub_extras import (
    format_daily_ops_snippet,
    format_relic_planner_hint,
    get_baro_wishlist_overlap,
    get_twitch_streaming_line,
    toggle_baro_wishlist,
)
from views import RefreshView, RetryView


def _hub_link_buttons() -> list[discord.ui.Button]:
    return list(baro_link_buttons()[:2])


async def _hub_cycle_panel_channel(guild_id: int) -> int | None:
    if not guild_id:
        return None
    try:
        from core.cycles_live import get_guild_cycle_panel_channel_id

        return await get_guild_cycle_panel_channel_id(guild_id)
    except Exception:
        return None


async def _fetch_hub_data(platform: str = "pc"):
    return await asyncio.gather(
        get_baro_status(),
        fetch_alerts(),
        get_all_cycles(),
        fetch_fissures(platform),
        fetch_sortie(),
        fetch_invasions(),
        fetch_steel_path(platform),
        fetch_arbitration(platform),
        fetch_nightwave(platform),
    )


def build_hub_embed(
    *,
    baro_active: bool,
    baro_data: dict,
    alerts_data: list,
    cycles_data: dict,
    fissures_data: list,
    client,
    platform: str = "pc",
    steel_path: dict | None = None,
    arbitration: dict | None = None,
    nightwave: dict | None = None,
    wishlist_line: str | None = None,
    twitch_line: str | None = None,
    guild_id: int | None = None,
    cycle_panel_channel_id: int | None = None,
) -> discord.Embed:
    """Compact hub card with daily ops, relic planner, and live status."""
    fields: list[tuple[str, str, bool]] = []
    if baro_data:
        _title, baro_val = _format_baro_summary(baro_data, baro_active)
        if wishlist_line:
            baro_val = f"{baro_val}\n{wishlist_line}"
        fields.append(("🛒 Baro", baro_val, True))
    else:
        fields.append(("🛒 Baro", "Unable to fetch", True))

    daily_ops = format_daily_ops_snippet(steel_path, arbitration, nightwave)
    fields.append(("📋 Daily Ops", daily_ops, True))

    alert_count = len(alerts_data or [])
    fissure_line = _format_fissures_summary(fissures_data or [])
    fields.append(
        ("📡 Live", f"**{alert_count}** alerts · {fissure_line}", True),
    )

    relic_hint = format_relic_planner_hint(fissures_data)
    fields.append(("💎 Relic planner", relic_hint, False))

    cycles = cycles_data or {}
    cycle_text = _format_cycles_summary(cycles)
    if cycle_panel_channel_id:
        cycle_text = f"{cycle_text}\n_Live panel: <#{cycle_panel_channel_id}>_"
    if len(cycle_text) > 200:
        cycle_text = cycle_text[:197] + "…"
    fields.append(("🌍 Cycles", cycle_text or "—", True))

    if twitch_line:
        fields.append(("📺 Streams", twitch_line, False))

    if guild_id and client:
        guild = client.get_guild(guild_id)
        if guild:
            music_line = format_guild_music_line(guild)
            if music_line:
                fields.append(("🎵 Clan radio", music_line, False))

    plat_note = warframe_footer_platform_note(platform, pc_only_api=platform == "pc")
    footer = f"{footer_for('warframe_hub')} · {plat_note}"

    return embed_template(
        "warframe_status",
        "🎮 Warframe Hub",
        "> Status snapshot · **`/warframe status`** for the full board",
        variant="world_state",
        platform=platform,
        client=client,
        fields=fields,
        footer=footer,
    )


class BaroWishlistModal(discord.ui.Modal, title="Baro wishlist item"):
    item = discord.ui.TextInput(
        label="Item name",
        placeholder="e.g. Primed Flow",
        max_length=120,
        required=True,
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        _added, msg = await toggle_baro_wishlist(
            self.guild_id, interaction.user.id, str(self.item),
        )
        await interaction.response.send_message(msg, ephemeral=True)


def _hub_view(interaction: discord.Interaction, platform: str, guild_id: int) -> discord.ui.View:
    async def on_refresh(btn_interaction: discord.Interaction):
        # Read-only public data — anyone may refresh.
        from api.warframe_api import invalidate

        invalidate("warframe:baro")
        invalidate("warframe:alerts")
        invalidate("warframe:cycles")
        br, ar, cr, fr, sr, ir, sp, arb, nw = await _fetch_hub_data(platform)
        ia, bd = br
        wishlist = None
        if bd and ia:
            inv = bd.get("inventory") or bd.get("Inventory") or []
            wishlist = await get_baro_wishlist_overlap(guild_id, inv)
        twitch = await get_twitch_streaming_line(guild_id)
        panel_ch = await _hub_cycle_panel_channel(guild_id)
        new_emb = build_hub_embed(
            baro_active=ia,
            baro_data=bd or {},
            alerts_data=ar or [],
            cycles_data=cr or {},
            fissures_data=fr or [],
            client=interaction.client,
            platform=platform,
            steel_path=sp,
            arbitration=arb,
            nightwave=nw,
            wishlist_line=wishlist,
            twitch_line=twitch,
            guild_id=guild_id,
            cycle_panel_channel_id=panel_ch,
        )
        from core.help_layout import help_layout_v2_enabled
        from core.warframe_hub_layout import WarframeHubLayout

        if help_layout_v2_enabled():
            try:
                fields = [(f.name, f.value, f.inline) for f in new_emb.fields]
                layout = WarframeHubLayout(
                    title=new_emb.title or "🎮 Warframe Hub",
                    intro=new_emb.description or "",
                    fields=fields,
                    on_refresh=on_refresh,
                )
                await btn_interaction.message.edit(view=layout)
                return
            except Exception:
                pass
        view = _hub_view(interaction, platform, guild_id)
        await btn_interaction.message.edit(embed=new_emb, view=view)

    view = RefreshView(on_refresh)
    add_link_row(view, _hub_link_buttons())

    wish = discord.ui.Button(
        label="Baro wishlist",
        style=discord.ButtonStyle.secondary,
        emoji="⭐",
        custom_id="wf_hub:baro_wish",
    )

    async def wish_cb(btn_interaction: discord.Interaction):
        if not btn_interaction.guild:
            return await btn_interaction.response.send_message("Server only.", ephemeral=True)
        await btn_interaction.response.send_modal(BaroWishlistModal(btn_interaction.guild.id))

    wish.callback = wish_cb  # type: ignore
    view.add_item(wish)

    hint = discord.ui.Button(
        label="Full status",
        style=discord.ButtonStyle.secondary,
        emoji="📋",
        custom_id="wf_hub:status_hint",
    )

    async def status_hint_cb(btn_interaction: discord.Interaction):
        await btn_interaction.response.send_message(
            "Run **`/warframe status`** for Baro, alerts, cycles, fissures, sortie, and invasions.",
            ephemeral=True,
        )

    hint.callback = status_hint_cb  # type: ignore
    view.add_item(hint)
    notify = discord.ui.Button(
        label="Notify setup",
        style=discord.ButtonStyle.primary,
        emoji="🔔",
        custom_id="wf_hub:notify_hint",
    )

    async def notify_hint_cb(btn_interaction: discord.Interaction):
        await btn_interaction.response.send_message(
            "Run **`/wfnotify configure`** — recommended wizard for Baro, cycles, and alerts.",
            ephemeral=True,
        )

    notify.callback = notify_hint_cb  # type: ignore
    view.add_item(notify)
    lfg = discord.ui.Button(
        label="Post LFG",
        style=discord.ButtonStyle.secondary,
        emoji="🤝",
        custom_id="wf_hub:lfg_hint",
    )

    async def lfg_hint_cb(btn_interaction: discord.Interaction):
        await btn_interaction.response.send_message(
            "Run **`/lfg`** to post a squad — or right-click a message → **Create LFG**.",
            ephemeral=True,
        )

    lfg.callback = lfg_hint_cb  # type: ignore
    view.add_item(lfg)
    return view


def setup(bot, group=None):
    """Register `/warframe hub` — refreshable member hub."""

    command_decorator = (
        group.command(
            name="hub",
            description="Warframe hub — Baro snippet, live status, notify setup, and LFG links.",
        )
        if group
        else bot.tree.command(
            name="warframe_hub",
            description="Warframe hub — Baro, status, notify, and LFG.",
        )
    )

    @command_decorator
    async def warframe_hub(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        platform = "pc"
        guild_id = interaction.guild.id if interaction.guild else 0
        if interaction.guild:
            platform = await resolve_warframe_platform(interaction.guild.id, interaction.user.id)

        results = await _fetch_hub_data(platform)
        baro_result, alerts_data, cycles_data, fissures_data = results[0], results[1], results[2], results[3]
        steel_path, arbitration, nightwave = results[6], results[7], results[8]
        is_active, baro_data = baro_result

        if not baro_data and not alerts_data and not cycles_data:
            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                br, ar, cr, fr, sr, ir, sp, arb, nw = await _fetch_hub_data(platform)
                ia, bd = br
                if not bd and not ar and not cr:
                    return await btn_interaction.message.edit(
                        embed=warframe_data_unavailable_embed(interaction.client),
                        view=None,
                    )
                wishlist = None
                if bd and ia:
                    inv = bd.get("inventory") or bd.get("Inventory") or []
                    wishlist = await get_baro_wishlist_overlap(guild_id, inv)
                twitch = await get_twitch_streaming_line(guild_id) if guild_id else None
                panel_ch = await _hub_cycle_panel_channel(guild_id) if guild_id else None
                emb = build_hub_embed(
                    baro_active=ia,
                    baro_data=bd or {},
                    alerts_data=ar or [],
                    cycles_data=cr or {},
                    fissures_data=fr or [],
                    client=interaction.client,
                    platform=platform,
                    steel_path=sp,
                    arbitration=arb,
                    nightwave=nw,
                    wishlist_line=wishlist,
                    twitch_line=twitch,
                    guild_id=guild_id,
                    cycle_panel_channel_id=panel_ch,
                )
                view = _hub_view(interaction, platform, guild_id)
                await btn_interaction.message.edit(embed=emb, view=view)

            return await interaction.edit_original_response(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=RetryView(on_retry),
            )

        wishlist_line = None
        if baro_data and is_active:
            inv = baro_data.get("inventory") or baro_data.get("Inventory") or []
            wishlist_line = await get_baro_wishlist_overlap(guild_id, inv)
        twitch_line = await get_twitch_streaming_line(guild_id) if guild_id else None
        panel_ch = await _hub_cycle_panel_channel(guild_id) if guild_id else None

        embed = build_hub_embed(
            baro_active=is_active,
            baro_data=baro_data or {},
            alerts_data=alerts_data or [],
            cycles_data=cycles_data or {},
            fissures_data=fissures_data or [],
            client=interaction.client,
            platform=platform,
            steel_path=steel_path,
            arbitration=arbitration,
            nightwave=nightwave,
            wishlist_line=wishlist_line,
            twitch_line=twitch_line,
            guild_id=guild_id,
            cycle_panel_channel_id=panel_ch,
        )
        view = _hub_view(interaction, platform, guild_id)
        from core.help_layout import help_layout_v2_enabled
        from core.warframe_hub_layout import WarframeHubLayout

        if help_layout_v2_enabled():
            try:
                # Re-use refresh handler from the classic view's first child callback chain
                refresh_cb = None
                for child in view.children:
                    if getattr(child, "label", None) == "Refresh":
                        refresh_cb = child.callback
                        break
                fields = [(f.name, f.value, f.inline) for f in embed.fields]
                layout = WarframeHubLayout(
                    title=embed.title or "🎮 Warframe Hub",
                    intro=embed.description or "",
                    fields=fields,
                    on_refresh=refresh_cb,
                )
                await interaction.edit_original_response(view=layout)
                return
            except Exception:
                pass
        await interaction.edit_original_response(embed=embed, view=view)
