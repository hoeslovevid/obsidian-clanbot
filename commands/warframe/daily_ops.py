"""Daily Ops: Steel Path, Arbitration, Nightwave."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser

from utils import obsidian_embed, EMBED_COLORS, format_number
from warframe_api import fetch_steel_path, fetch_arbitration, fetch_nightwave
from views import RetryView, RefreshView
from cache_utils import invalidate


def _fmt_expiry(expiry_str: str) -> str:
    try:
        exp = dateparser.parse(expiry_str, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        if not exp:
            return ""
        return f"<t:{int(exp.timestamp())}:R>"
    except Exception:
        return ""


def setup(bot, group=None):
    cmd = group.command(name="daily_ops", description="Steel Path, Arbitration, and Nightwave challenges.") if group else bot.tree.command(name="daily_ops", description="Steel Path, Arbitration, and Nightwave challenges.")

    @cmd
    async def daily_ops(interaction: discord.Interaction):
        await interaction.response.defer()
        import asyncio
        sp, arb, nw = await asyncio.gather(fetch_steel_path(), fetch_arbitration(), fetch_nightwave())
        if sp is None and arb is None and nw is None:
            async def on_retry(btn_i: discord.Interaction):
                if btn_i.user.id != interaction.user.id:
                    return await btn_i.response.send_message("Only the requester can retry.", ephemeral=True)
                await btn_i.response.defer()
                sp2, arb2, nw2 = await asyncio.gather(fetch_steel_path(), fetch_arbitration(), fetch_nightwave())
                emb = _build_embed(sp2, arb2, nw2, interaction.client)
                await btn_i.message.edit(embed=emb, view=None)
            return await interaction.followup.send(
                embed=obsidian_embed("❌ Error", "Could not fetch daily ops data.", color=discord.Color.red(), client=interaction.client),
                view=RetryView(on_retry),
            )
        embed = _build_embed(sp, arb, nw, interaction.client)

        async def on_refresh(btn_i: discord.Interaction):
            if btn_i.user.id != interaction.user.id:
                return await btn_i.response.send_message("Only the requester can refresh.", ephemeral=True)
            await btn_i.response.defer()
            invalidate("warframe:steelPath")
            invalidate("warframe:arbitration")
            invalidate("warframe:nightwave")
            sp2, arb2, nw2 = await asyncio.gather(fetch_steel_path(), fetch_arbitration(), fetch_nightwave())
            emb = _build_embed(sp2, arb2, nw2, interaction.client)
            await btn_i.message.edit(embed=emb, view=RefreshView(on_refresh, timeout=300))

        await interaction.followup.send(embed=embed, view=RefreshView(on_refresh, timeout=300))


def _build_embed(sp, arb, nw, client):
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
    return obsidian_embed(
        "📋 Daily Ops",
        "Steel Path, Arbitration, and Nightwave.",
        color=EMBED_COLORS["warframe"],
        fields=fields,
        footer="See also: /warframe sortie, /warframe fissures • warframestat.us",
        client=client,
    )
