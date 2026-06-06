"""Refreshable Warframe hub — status snippet, Baro, notify, and LFG links."""
from __future__ import annotations

import asyncio

import discord  # type: ignore
from api.warframe_api import (
    fetch_alerts,
    fetch_fissures,
    fetch_invasions,
    fetch_sortie,
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
from views import RefreshView, RetryView


def _hub_link_buttons() -> list[discord.ui.Button]:
    return list(baro_link_buttons()[:2])


async def _fetch_hub_data():
    return await asyncio.gather(
        get_baro_status(),
        fetch_alerts(),
        get_all_cycles(),
        fetch_fissures(),
        fetch_sortie(),
        fetch_invasions(),
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
) -> discord.Embed:
    """Compact hub card — ≤3 inline fields above the fold."""
    fields: list[tuple[str, str, bool]] = []
    if baro_data:
        _title, baro_val = _format_baro_summary(baro_data, baro_active)
        fields.append(("🛒 Baro", baro_val, True))
    else:
        fields.append(("🛒 Baro", "Unable to fetch", True))

    alert_count = len(alerts_data or [])
    fissure_line = _format_fissures_summary(fissures_data or [])
    fields.append(
        (
            "📡 Live",
            f"**{alert_count}** alerts · {fissure_line}",
            True,
        )
    )

    cycles = cycles_data or {}
    cycle_text = _format_cycles_summary(cycles)
    if len(cycle_text) > 200:
        cycle_text = cycle_text[:197] + "…"
    fields.append(("🌍 Cycles", cycle_text or "—", True))

    plat_note = warframe_footer_platform_note(platform, pc_only_api=True)
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

    async def _hub_impl(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        platform = "pc"
        if interaction.guild:
            platform = await resolve_warframe_platform(interaction.guild.id, interaction.user.id)

        baro_result, alerts_data, cycles_data, fissures_data, _sortie_data, _invasions_data = await _fetch_hub_data()
        is_active, baro_data = baro_result

        if not baro_data and not alerts_data and not cycles_data:
            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                br, ar, cr, fr, sr, ir = await _fetch_hub_data()
                ia, bd = br
                if not bd and not ar and not cr:
                    return await btn_interaction.message.edit(
                        embed=warframe_data_unavailable_embed(interaction.client),
                        view=None,
                    )
                emb = build_hub_embed(
                    baro_active=ia,
                    baro_data=bd or {},
                    alerts_data=ar or [],
                    cycles_data=cr or {},
                    fissures_data=fr or [],
                    client=interaction.client,
                    platform=platform,
                )
                view = _hub_view(interaction, platform)
                await btn_interaction.message.edit(embed=emb, view=view)

            return await interaction.edit_original_response(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=RetryView(on_retry),
            )

        embed = build_hub_embed(
            baro_active=is_active,
            baro_data=baro_data or {},
            alerts_data=alerts_data or [],
            cycles_data=cycles_data or {},
            fissures_data=fissures_data or [],
            client=interaction.client,
            platform=platform,
        )
        view = _hub_view(interaction, platform)
        await interaction.edit_original_response(embed=embed, view=view)

    def _hub_view(interaction: discord.Interaction, platform: str) -> discord.ui.View:
        async def on_refresh(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            await btn_interaction.response.defer()
            from api.warframe_api import invalidate

            invalidate("warframe:baro")
            invalidate("warframe:alerts")
            invalidate("warframe:cycles")
            br, ar, cr, fr, sr, ir = await _fetch_hub_data()
            ia, bd = br
            new_emb = build_hub_embed(
                baro_active=ia,
                baro_data=bd or {},
                alerts_data=ar or [],
                cycles_data=cr or {},
                fissures_data=fr or [],
                client=interaction.client,
                platform=platform,
            )
            view = _hub_view(interaction, platform)
            await btn_interaction.message.edit(embed=new_emb, view=view)

        view = RefreshView(on_refresh)
        add_link_row(view, _hub_link_buttons())
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

    @command_decorator
    async def warframe_hub(interaction: discord.Interaction):
        await _hub_impl(interaction)
