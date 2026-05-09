"""What's Happening Now - Baro + Alerts + Cycles in one embed."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser

from core.utils import obsidian_embed, warframe_data_unavailable_embed, BUTTON_ONLY_RUNNER_MSG
from api.warframe_api import get_baro_status, fetch_alerts, get_all_cycles, fetch_fissures, fetch_sortie, fetch_invasions
from commands.warframe.alerts import format_alert_rewards
from views import RetryView, RefreshView
from core.cache_utils import invalidate


def _format_baro_summary(baro_data: dict, is_active: bool) -> tuple[str, str]:
    """Return (title, value) for Baro in status embed."""
    location = baro_data.get("location", "Unknown")
    expiry = baro_data.get("expiry", "")
    activation = baro_data.get("activation", "")
    
    if is_active:
        try:
            expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            ts = int(expiry_time.timestamp()) if expiry_time else 0
            value = f"📍 {location}\n⏰ Ends <t:{ts}:R>"
        except Exception:
            value = f"📍 {location}\n⏰ Unknown expiry"
        return "🛒 Baro Ki'Teer", f"🟢 Active\n{value}"
    
    if activation:
        try:
            act_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            ts = int(act_time.timestamp()) if act_time else 0
            value = f"📍 {location}\n⏰ Arrives <t:{ts}:R>"
        except Exception:
            value = f"📍 {location}"
        return "🛒 Baro Ki'Teer", f"🔴 Not active\n{value}"
    
    return "🛒 Baro Ki'Teer", f"🔴 Not active\n📍 {location}"


def _format_alerts_summary(alerts_data: list) -> str:
    """Format alerts for status embed."""
    if not alerts_data:
        return "No active alerts"
    
    count = len(alerts_data)
    lines = []
    for alert in alerts_data[:3]:
        mission = alert.get("mission", {})
        node = mission.get("node", "?")
        expiry = alert.get("expiry", "")
        try:
            exp = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            ts = int(exp.timestamp()) if exp else 0
            time_str = f"<t:{ts}:R>" if ts else "?"
        except Exception:
            time_str = "?"
        rewards = (format_alert_rewards(alert) or "—")[:80]
        lines.append(f"• **{node}** — {time_str}\n  _{rewards}_")
    
    result = f"**{count} active**\n" + "\n".join(lines)
    if count > 3:
        result += f"\n_+{count - 3} more_"
    return result


def _format_cycles_summary(cycles_data: dict) -> str:
    """Format cycles for status embed."""
    parts = []
    if cycles_data.get("cetus"):
        c = cycles_data["cetus"]
        state = "☀️ Day" if c.get("isDay") else "🌙 Night"
        exp = c.get("expiry", "")
        try:
            e = dateparser.parse(exp, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            ts = int(e.timestamp()) if e else 0
            parts.append(f"🌅 Cetus: {state} <t:{ts}:R>")
        except Exception:
            parts.append(f"🌅 Cetus: {state}")
    if cycles_data.get("vallis"):
        v = cycles_data["vallis"]
        state = "🔥 Warm" if v.get("isWarm") else "❄️ Cold"
        exp = v.get("expiry", "")
        try:
            e = dateparser.parse(exp, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            ts = int(e.timestamp()) if e else 0
            parts.append(f"❄️ Fortuna: {state} <t:{ts}:R>")
        except Exception:
            parts.append(f"❄️ Fortuna: {state}")
    if cycles_data.get("cambion"):
        cam = cycles_data["cambion"]
        state = cam.get("state", "?").title()
        exp = cam.get("expiry", "")
        try:
            e = dateparser.parse(exp, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            ts = int(e.timestamp()) if e else 0
            parts.append(f"🦠 Deimos: {state} <t:{ts}:R>")
        except Exception:
            parts.append(f"🦠 Deimos: {state}")
    
    return "\n".join(parts) if parts else "No cycle data"


def _format_fissures_summary(fissures: list) -> str:
    """Compact fissures summary."""
    if not fissures:
        return "None active"
    count = len(fissures)
    steel = sum(1 for f in fissures if f.get("isHard"))
    return f"**{count}** fissures ({steel} Steel Path)"


def _format_invasions_summary(invasions: list) -> str:
    """Compact invasions summary — count active and note any with worthwhile rewards."""
    if not invasions:
        return "None active"
    active = [inv for inv in invasions if not inv.get("completed", True)]
    if not active:
        return "None active"
    count = len(active)
    # Highlight invasions that offer forma, orokin, or catalyst/reactor
    keywords = ("forma", "orokin", "catalyst", "reactor", "nitain", "kuva")
    notable = []
    for inv in active[:5]:
        desc = (inv.get("desc") or "").lower()
        atk = (inv.get("attackerReward", {}) or {})
        def_r = (inv.get("defenderReward", {}) or {})
        reward_items = []
        for side in (atk, def_r):
            for ct in side.get("countedItems", []):
                reward_items.append((ct.get("type") or ct.get("key") or "").lower())
        all_text = desc + " ".join(reward_items)
        if any(k in all_text for k in keywords):
            node = inv.get("node", "?")
            notable.append(node)
    result = f"**{count}** active"
    if notable:
        result += f"\n⭐ Notable: {', '.join(notable[:3])}"
    return result


def _format_sortie_summary(sortie_data: dict) -> str:
    """Compact sortie summary."""
    if not sortie_data:
        return "No data"
    missions = sortie_data.get("variants", [])
    if not missions:
        return "No sortie"
    expiry = sortie_data.get("expiry", "")
    try:
        e = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        ts = int(e.timestamp()) if e else 0
        return f"**{len(missions)}** missions • <t:{ts}:R>"
    except Exception:
        return f"**{len(missions)}** missions"


def build_status_embed(baro_active: bool, baro_data: dict, alerts_data: list, cycles_data: dict, fissures_data: list, sortie_data: dict, client, invasions_data: list | None = None) -> discord.Embed:
    """Build the combined status embed."""
    now = datetime.now(timezone.utc)
    footer_ts = int(now.timestamp())
    footer = f"Last updated <t:{footer_ts}:R> • PC data • Use Refresh to update"
    
    fields = []
    
    # Baro
    if baro_data:
        title, value = _format_baro_summary(baro_data, baro_active)
        fields.append((title, value, True))
    else:
        fields.append(("🛒 Baro Ki'Teer", "Unable to fetch", True))
    
    # Alerts
    alerts = alerts_data if alerts_data else []
    fields.append(("📢 Alerts", _format_alerts_summary(alerts), True))
    
    # Cycles
    cycles = cycles_data or {}
    fields.append(("🌍 Cycles", _format_cycles_summary(cycles), True))

    # Fissures
    fissures = fissures_data or []
    fields.append(("⚡ Fissures", _format_fissures_summary(fissures), True))

    # Sortie
    sortie = sortie_data or {}
    fields.append(("🎯 Sortie", _format_sortie_summary(sortie), True))

    # Invasions
    if invasions_data is not None:
        fields.append(("⚔️ Invasions", _format_invasions_summary(invasions_data), True))

    embed = obsidian_embed(
        "📋 What's Happening Now",
        "> Baro · Alerts · Cycles · Fissures · Sortie",
        category="warframe",
        fields=fields,
        footer=footer,
        client=client,
    )
    return embed


def setup(bot, group=None):
    """Register the status command."""
    command_decorator = (
        group.command(name="status", description="Baro + Alerts + Cycles in one embed")
        if group
        else bot.tree.command(name="status", description="Baro + Alerts + Cycles in one embed")
    )

    async def _status_impl(interaction: discord.Interaction):
        """Display Baro, alerts, and cycles in one embed."""
        await interaction.response.defer(ephemeral=False)

        import asyncio
        baro_result, alerts_data, cycles_data, fissures_data, sortie_data, invasions_data = await asyncio.gather(
            get_baro_status(), fetch_alerts(), get_all_cycles(), fetch_fissures(), fetch_sortie(), fetch_invasions(),
        )
        is_active, baro_data = baro_result

        if not baro_data and not alerts_data and not cycles_data and not fissures_data and not sortie_data:
            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                invalidate("warframe:baro")
                invalidate("warframe:alerts")
                invalidate("warframe:cycles")
                br, ar, cr, fr, sr, ir = await asyncio.gather(
                    get_baro_status(), fetch_alerts(), get_all_cycles(), fetch_fissures(), fetch_sortie(), fetch_invasions(),
                )
                ia, bd = br
                emb = build_status_embed(ia, bd, ar, cr, fr, sr, interaction.client, ir)
                await btn_interaction.message.edit(embed=emb, view=None)
            return await interaction.edit_original_response(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=RetryView(on_retry),
            )

        embed = build_status_embed(
            is_active, baro_data or {}, alerts_data or [], cycles_data or {},
            fissures_data or [], sortie_data or {}, interaction.client, invasions_data or [],
        )

        async def on_refresh(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            await btn_interaction.response.defer()
            invalidate("warframe:baro")
            invalidate("warframe:alerts")
            invalidate("warframe:cycles")
            br, ar, cr, fr, sr, ir = await asyncio.gather(
                get_baro_status(), fetch_alerts(), get_all_cycles(), fetch_fissures(), fetch_sortie(), fetch_invasions(),
            )
            ia, bd = br
            new_emb = build_status_embed(ia, bd or {}, ar or [], cr or {}, fr or [], sr or {}, interaction.client, ir or [])
            view = RefreshView(on_refresh)
            await btn_interaction.message.edit(embed=new_emb, view=view)

        view = RefreshView(on_refresh)
        await interaction.edit_original_response(embed=embed, view=view)

    @command_decorator
    async def status(interaction: discord.Interaction):
        await _status_impl(interaction)

    # Alias: /warframe wf
    wf_decorator = (
        group.command(name="wf", description="Baro + Alerts + Cycles (alias for status)")
        if group
        else bot.tree.command(name="wf", description="Baro + Alerts + Cycles (alias for status)")
    )
    @wf_decorator
    async def wf(interaction: discord.Interaction):
        await _status_impl(interaction)
