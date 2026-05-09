"""Void Fissures command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from core.utils import obsidian_embed, EMBED_COLORS, format_number, warframe_data_unavailable_embed, BUTTON_ONLY_RUNNER_MSG
from api.warframe_api import fetch_fissures
from views import RetryView, RefreshView
from core.cache_utils import invalidate


def _fmt_time(expiry_str: str) -> str:
    try:
        import dateparser
        exp = dateparser.parse(expiry_str, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        if not exp:
            return "?"
        delta = exp - datetime.now(timezone.utc)
        if delta.total_seconds() <= 0:
            return "Expired"
        s = int(delta.total_seconds())
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        if h:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return "?"


def setup(bot, group=None):
    cmd = group.command(name="fissures", description="View active Void Fissure missions.") if group else bot.tree.command(name="fissures", description="View active Void Fissure missions.")

    @cmd
    async def fissures(interaction: discord.Interaction):
        await interaction.response.defer()
        data = await fetch_fissures()
        if data is None:
            async def on_retry(btn_i: discord.Interaction):
                if btn_i.user.id != interaction.user.id:
                    return await btn_i.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_i.response.defer()
                nd = await fetch_fissures()
                if nd is None:
                    return await btn_i.followup.send(
                        "Still can't load fissures. Try **Try again** again in a bit.",
                        ephemeral=True,
                    )
                emb = _build_embed(nd, interaction.client)
                await btn_i.message.edit(embed=emb, view=None)
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=RetryView(on_retry),
            )
        if not data:
            return await interaction.followup.send(
                embed=obsidian_embed("⚡ Void Fissures", "No active fissures.", color=EMBED_COLORS["warframe"], client=interaction.client),
            )
        embed = _build_embed(data, interaction.client)

        async def on_refresh(btn_i: discord.Interaction):
            if btn_i.user.id != interaction.user.id:
                return await btn_i.response.send_message("Only the requester can refresh.", ephemeral=True)
            await btn_i.response.defer()
            invalidate("warframe:fissures")
            nd = await fetch_fissures()
            if nd is None:
                return await btn_i.followup.send(
                    "Couldn't refresh fissures yet — stats API is still having issues.",
                    ephemeral=True,
                )
            emb = _build_embed(nd, interaction.client)
            await btn_i.message.edit(embed=emb, view=RefreshView(on_refresh, timeout=300))

        await interaction.followup.send(embed=embed, view=RefreshView(on_refresh, timeout=300))


def _build_embed(fissures_list, client):
    lines = []
    tier_emoji = {"Lith": "🟢", "Meso": "🟡", "Neo": "🔵", "Axi": "🟣"}
    for f in fissures_list[:15]:
        node = f.get("node", "?")
        tier = f.get("tier", "?")
        mission = f.get("missionType", "?")
        enemy = f.get("enemy", "?")
        eta = _fmt_time(f.get("expiry", ""))
        em = tier_emoji.get(tier, "⚪")
        lines.append(f"{em} **{node}** — {tier} {mission} ({enemy}) • {eta}")
    if len(fissures_list) > 15:
        lines.append(f"_...and {format_number(len(fissures_list) - 15)} more_")
    desc = "\n".join(lines) if lines else "No active fissures."
    return obsidian_embed(
        "⚡ Void Fissures",
        desc,
        color=EMBED_COLORS["warframe"],
        footer=f"See also: /warframe sortie, /warframe baro • warframestat.us",
        client=client,
    )
