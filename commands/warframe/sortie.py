"""Sortie command."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser

from core.utils import obsidian_embed, EMBED_COLORS, warframe_data_unavailable_embed
from core.wf_resolve import (
    wf_fetch_failed,
    wf_footer,
    wf_invalidate,
    wf_retry_denied,
    wf_retry_guard,
)
from api.warframe_api import fetch_sortie
from core.refresh_panels import register_refresh_panel
from views import RetryView, RefreshView

SORTIE_CACHE_KEY = "warframe:sortie"


def setup(bot, group=None):
    cmd = group.command(name="sortie", description="View today's Sortie missions.") if group else bot.tree.command(name="sortie", description="View today's Sortie missions.")

    @cmd
    async def sortie(interaction: discord.Interaction):
        await interaction.response.defer()
        data = await fetch_sortie()
        if wf_fetch_failed(data):
            async def on_retry(btn_i: discord.Interaction):
                if not wf_retry_guard(btn_i, interaction.user.id):
                    return await wf_retry_denied(btn_i)
                await btn_i.response.defer()
                nd = await fetch_sortie()
                if wf_fetch_failed(nd):
                    return await btn_i.followup.send("Still unable to fetch.", ephemeral=True)
                emb = _build_embed(nd, interaction.client)
                await btn_i.message.edit(embed=emb, view=None)
            from core.wf_recovery import attach_notify_when_back
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=attach_notify_when_back(RetryView(on_retry)),
            )
        embed = _build_embed(data, interaction.client)

        view = RefreshView.panel("wf_sortie")
        msg = await interaction.followup.send(embed=embed, view=view)
        await register_refresh_panel(msg, "wf_sortie", {})


def _build_embed(data, client):
    boss = data.get("boss", "Unknown")
    faction = data.get("faction", "Unknown")
    missions = data.get("missions", [])
    expiry = data.get("expiry", "")
    try:
        exp_dt = dateparser.parse(expiry, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
        exp_ts = int(exp_dt.timestamp()) if exp_dt else 0
        time_line = "Resets: <t:{}:R> (<t:{}:f>)".format(exp_ts, exp_ts) if exp_ts else ""
    except Exception:
        time_line = ""

    lines = ["**Boss:** {} | **Faction:** {}".format(boss, faction)]
    if time_line:
        lines.append(time_line)
    lines.append("")
    for i, m in enumerate(missions, 1):
        mod = m.get("modifier", "?")
        mod_desc = m.get("modifierDescription", "")
        node = m.get("node", "?")
        mission_type = m.get("missionType", "?")
        lines.append("**{}. {}** ({})".format(i, node, mission_type))
        lines.append("   _Modifier:_ {}".format(mod))
        if mod_desc:
            lines.append("   {}...".format(mod_desc[:120]) if len(mod_desc) > 120 else "   {}".format(mod_desc))
    desc = "\n".join(lines) if lines else "No sortie data."
    return obsidian_embed(
        "Today's Sortie",
        desc,
        color=EMBED_COLORS["warframe"],
        footer=wf_footer("See also: /warframe fissures, /warframe daily_ops", SORTIE_CACHE_KEY),
        client=client,
    )
