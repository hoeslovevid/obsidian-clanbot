"""Daily Ops: Steel Path, Arbitration, Nightwave."""
from __future__ import annotations

import asyncio

import discord
import dateparser

from core.embed_footers import footer_for
from core.utils import obsidian_embed, EMBED_COLORS, warframe_data_unavailable_embed
from core.wf_resolve import (
    wf_daily_ops_cache_keys,
    wf_fetch_failed,
    wf_invalidate_daily_ops,
    wf_platform_for,
    wf_retry_denied,
    wf_retry_guard,
)
from core.wf_copy import merge_wf_footer
from api.warframe_api import fetch_steel_path, fetch_arbitration, fetch_nightwave
from views import RetryView, RefreshView
from core.cache_utils import freshness_note, peek_cached


def _fmt_expiry(expiry_str: str) -> str:
    try:
        exp = dateparser.parse(expiry_str, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        if not exp:
            return ""
        return f"<t:{int(exp.timestamp())}:R>"
    except Exception:
        return ""


async def _pull_daily_ops(plat: str) -> tuple:
    return await asyncio.gather(
        fetch_steel_path(plat),
        fetch_arbitration(plat),
        fetch_nightwave(plat),
    )


async def _fetch_daily_ops(guild_id: int | None, user_id: int) -> tuple:
    plat = await wf_platform_for(guild_id, user_id)
    sp_key, arb_key, nw_key = wf_daily_ops_cache_keys(plat)
    sp_p = peek_cached(sp_key)
    arb_p = peek_cached(arb_key)
    nw_p = peek_cached(nw_key)
    if sp_p is not None and arb_p is not None and nw_p is not None:
        asyncio.create_task(_pull_daily_ops(plat))
        return (sp_p, arb_p, nw_p), plat
    results = await _pull_daily_ops(plat)
    return results, plat


def _all_daily_ops_failed(sp, arb, nw) -> bool:
    return wf_fetch_failed(sp) and wf_fetch_failed(arb) and wf_fetch_failed(nw)


def setup(bot, group=None):
    cmd = group.command(name="daily_ops", description="Steel Path, Arbitration, and Nightwave challenges.") if group else bot.tree.command(name="daily_ops", description="Steel Path, Arbitration, and Nightwave challenges.")

    @cmd
    async def daily_ops(interaction: discord.Interaction):
        await interaction.response.defer()
        gid = interaction.guild.id if interaction.guild else None
        (sp, arb, nw), plat = await _fetch_daily_ops(gid, interaction.user.id)
        if _all_daily_ops_failed(sp, arb, nw):
            async def on_retry(btn_i: discord.Interaction):
                if not wf_retry_guard(btn_i, interaction.user.id):
                    return await wf_retry_denied(btn_i)
                await btn_i.response.defer()
                (sp2, arb2, nw2), plat2 = await _fetch_daily_ops(gid, interaction.user.id)
                if _all_daily_ops_failed(sp2, arb2, nw2):
                    return await btn_i.followup.send(
                        "Still can't load daily ops. Try **Try again** again in a bit.",
                        ephemeral=True,
                    )
                emb = _build_embed(sp2, arb2, nw2, interaction.client, platform=plat2)
                await btn_i.message.edit(embed=emb, view=None)
            from core.wf_recovery import attach_notify_when_back
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=attach_notify_when_back(RetryView(on_retry)),
            )
        embed = _build_embed(sp, arb, nw, interaction.client, platform=plat)

        async def on_refresh(btn_i: discord.Interaction):
            await wf_invalidate_daily_ops(plat)
            (sp2, arb2, nw2), plat2 = await _fetch_daily_ops(gid, interaction.user.id)
            emb = _build_embed(sp2, arb2, nw2, interaction.client, platform=plat2)
            await btn_i.message.edit(embed=emb, view=RefreshView(on_refresh, timeout=300))

        await interaction.followup.send(embed=embed, view=RefreshView(on_refresh, timeout=300))


def _build_embed(sp, arb, nw, client, *, platform: str = "pc"):
    fields = []

    if sp:
        reward = sp.get("currentReward", {}).get("name", "?") if isinstance(sp.get("currentReward"), dict) else str(sp.get("currentReward", "?"))
        exp = _fmt_expiry(sp.get("expiry", ""))
        fields.append(("🔴 Steel Path", f"**Reward:** {reward}\nExpires: {exp or '?'}", True))

    if arb:
        node = arb.get("node", "?")
        a_type = arb.get("type", "?")
        enemy = arb.get("enemy", "?")
        exp = _fmt_expiry(arb.get("expiry", ""))
        fields.append(("⚔️ Arbitration", f"**{node}** ({a_type})\nEnemy: {enemy}\nExpires: {exp or '?'}", True))

    if nw:
        daily = nw.get("dailyChallenges", []) or nw.get("activeChallenges", []) or []
        weekly = nw.get("weeklyChallenges", []) or []
        if not daily and not weekly and nw.get("activeChallenges"):
            ac = nw["activeChallenges"]
            daily = [c for c in ac if c.get("isDaily")] if isinstance(ac, list) else []
            weekly = [c for c in ac if not c.get("isDaily")] if isinstance(ac, list) else []
        season = nw.get("season", nw.get("seasonTag", 0))
        def _challenge_title(c):
            return c.get("title") or c.get("desc") or str(c)[:60]
        d_lines = [f"• {_challenge_title(c)}" for c in (daily if isinstance(daily, list) else [])[:5]]
        w_lines = [f"• {_challenge_title(c)}" for c in (weekly if isinstance(weekly, list) else [])[:5]]
        nw_text = f"**Season {season}**\n"
        if d_lines:
            nw_text += "**Daily:**\n" + "\n".join(d_lines) + "\n\n"
        if w_lines:
            nw_text += "**Weekly:**\n" + "\n".join(w_lines)
        if len(nw_text.strip()) > 10:
            fields.append(("🌙 Nightwave", nw_text[:1020] + ("..." if len(nw_text) > 1020 else ""), False))

    if not fields:
        return obsidian_embed("📋 Daily Ops", "No data available.", color=EMBED_COLORS["warframe"], client=client)

    sp_key, arb_key, nw_key = wf_daily_ops_cache_keys(platform)
    age_note = freshness_note(sp_key) or freshness_note(arb_key) or freshness_note(nw_key)
    footer = merge_wf_footer(
        f"{footer_for('warframe_hub')} · /warframe sortie, /warframe fissures{age_note}",
        "warframe:daily_ops",
    )
    return obsidian_embed(
        "📋 Daily Ops",
        "Steel Path, Arbitration, and Nightwave.",
        color=EMBED_COLORS["warframe"],
        fields=fields,
        footer=footer,
        client=client,
    )
