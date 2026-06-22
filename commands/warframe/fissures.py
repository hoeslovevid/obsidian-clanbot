"""Void Fissures command."""
import discord
from discord import app_commands
from datetime import datetime, timezone
from typing import Optional

from core.utils import obsidian_embed, EMBED_COLORS, format_number, warframe_data_unavailable_embed, BUTTON_ONLY_RUNNER_MSG
from core.wf_resolve import (
    wf_fetch_failed,
    wf_footer,
    wf_invalidate,
    wf_platform,
)
from api.warframe_api import fetch_fissures
from views import RefreshView
from core.refresh_panels import register_refresh_panel
from core.wf_retry_panels import send_wf_retry_message

FISSURE_TIER_CHOICES = [
    app_commands.Choice(name="All tiers", value="all"),
    app_commands.Choice(name="Lith", value="Lith"),
    app_commands.Choice(name="Meso", value="Meso"),
    app_commands.Choice(name="Neo", value="Neo"),
    app_commands.Choice(name="Axi", value="Axi"),
    app_commands.Choice(name="Requiem", value="Requiem"),
]


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
    cmd = group.command(name="fissures", description="Void fissure missions — Lith, Meso, Neo, Axi, Requiem tiers.") if group else bot.tree.command(name="fissures", description="View active Void Fissure missions.")

    @cmd
    @app_commands.describe(tier="Filter by relic tier (default: your saved preset or all)")
    @app_commands.choices(tier=FISSURE_TIER_CHOICES)
    async def fissures(interaction: discord.Interaction, tier: Optional[app_commands.Choice[str]] = None):
        if interaction.guild and tier is None:
            from core.user_prefs import default_fissure_tier

            saved = await default_fissure_tier(interaction.guild.id, interaction.user.id)
            tier_filter = saved or "all"
        else:
            tier_filter = tier.value if tier else "all"
        await interaction.response.defer()
        platform = await wf_platform(interaction)
        cache_key = f"warframe:fissures:{platform}"
        data = await fetch_fissures(platform)
        if wf_fetch_failed(data):
            fiss_payload = {"platform": platform, "tier_filter": tier_filter}
            return await send_wf_retry_message(
                interaction,
                embed=warframe_data_unavailable_embed(interaction.client),
                retry_type="wf_fissures",
                payload=fiss_payload,
                owner_user_id=interaction.user.id,
                fetch_probe=lambda: fetch_fissures(platform),
                edit=False,
            )
        if not data:
            return await interaction.followup.send(
                embed=obsidian_embed("⚡ Void Fissures", "No active fissures.", color=EMBED_COLORS["warframe"], client=interaction.client),
            )
        embed = _build_embed(data, interaction.client, tier_filter=tier_filter, cache_key=cache_key)
        payload = {"platform": platform, "tier_filter": tier_filter}
        view = RefreshView.panel("wf_fissures", payload=payload)
        msg = await interaction.followup.send(embed=embed, view=view)
        await register_refresh_panel(msg, "wf_fissures", payload)


def _filter_by_tier(fissures_list: list, tier_filter: str) -> list:
    if not tier_filter or tier_filter == "all":
        return fissures_list
    return [f for f in fissures_list if (f.get("tier") or "").lower() == tier_filter.lower()]


def _build_embed(fissures_list, client, *, tier_filter: str = "all", cache_key: str = "warframe:fissures:pc"):
    fissures_list = _filter_by_tier(fissures_list, tier_filter)
    if tier_filter and tier_filter != "all" and not fissures_list:
        return obsidian_embed(
            "⚡ Void Fissures",
            f"No active **{tier_filter}** fissures right now.\n\nTry another tier or check back later.",
            color=EMBED_COLORS["warframe"],
            footer=wf_footer("See also: /warframe sortie, /warframe baro", cache_key),
            client=client,
        )

    lines = []
    tier_emoji = {"Lith": "🟢", "Meso": "🟡", "Neo": "🔵", "Axi": "🟣"}

    # Separate normal, Steel Path, and Void Storm fissures
    normal   = [f for f in fissures_list if not f.get("isHard") and not f.get("isStorm")]
    sp       = [f for f in fissures_list if f.get("isHard")]
    storms   = [f for f in fissures_list if f.get("isStorm")]

    is_fallback = any("isStorm" in f for f in fissures_list) or (
        # Fallback data uses plain planet names (no parenthetical node detail)
        fissures_list and "(" not in fissures_list[0].get("node", "(")
    )

    def _fmt_entry(f: dict, idx: int) -> str:
        node   = f.get("node", "?")
        tier   = f.get("tier", "?")
        mission = f.get("missionType", "?")
        enemy  = f.get("enemy", "?")
        eta    = _fmt_time(f.get("expiry", ""))
        em     = tier_emoji.get(tier, "⚪")
        storm  = " ⚡Storm" if f.get("isStorm") else ""
        return f"{em} **{node}** — {tier} {mission} ({enemy}){storm} • {eta}"

    if normal:
        lines.append("**Normal Fissures**")
        lines += [_fmt_entry(f, i) for i, f in enumerate(normal[:8])]
    if sp:
        lines.append("\n**🗡️ Steel Path Fissures**")
        lines += [_fmt_entry(f, i) for i, f in enumerate(sp[:8])]
    if storms:
        lines.append("\n**⚡ Void Storms (Railjack)**")
        lines += [_fmt_entry(f, i) for i, f in enumerate(storms[:4])]

    total = len(fissures_list)
    shown = min(8, len(normal)) + min(8, len(sp)) + min(4, len(storms))
    if total > shown:
        lines.append(f"_...and {format_number(total - shown)} more_")

    desc = "\n".join(lines) if lines else "No active fissures."

    note = " • ⚠️ Approx. locations (API unavailable)" if is_fallback else ""
    if tier_filter and tier_filter != "all":
        note = f" • Filter: {tier_filter}{note}"
    preset_header = ""
    if tier_filter and tier_filter != "all":
        preset_header = (
            f"_Showing **{tier_filter}** fissures — change preset in `/preferences fissure_tier`_\n\n"
        )
    base_footer = f"See also: /warframe sortie, /warframe baro{note}"
    return obsidian_embed(
        "⚡ Void Fissures",
        preset_header + desc,
        color=EMBED_COLORS["warframe"],
        footer=wf_footer(base_footer, cache_key),
        client=client,
    )
