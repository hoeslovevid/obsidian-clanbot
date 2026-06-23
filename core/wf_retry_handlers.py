"""Retry dispatch for persistent Warframe failure panels."""
from __future__ import annotations

import asyncio
from typing import Any

import discord

from api.warframe_api import (
    fetch_alerts,
    fetch_duviri_circuit,
    fetch_fissures,
    fetch_invasions,
    fetch_sortie,
    get_all_cycles,
    get_baro_status,
)
from core.refresh_panels import register_refresh_panel
from core.utils import warframe_data_unavailable_embed
from core.wf_resolve import wf_fetch_failed, wf_invalidate_status_snapshot
from views import RefreshView


async def _edit_success(
    interaction: discord.Interaction,
    embed: discord.Embed,
    *,
    panel_type: str,
    payload: dict[str, Any] | None = None,
    view: discord.ui.View | None = None,
) -> bool:
    active_view = view or RefreshView.panel(panel_type, payload=payload or {})
    if not interaction.message:
        return False
    await interaction.message.edit(embed=embed, view=active_view)
    await register_refresh_panel(interaction.message, panel_type, payload)
    return True


async def retry_wf_hub(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.hub import (
        _fetch_hub_data,
        _hub_cycle_panel_channel,
        _hub_view,
        build_hub_embed,
    )
    from core.wf_hub_extras import get_baro_wishlist_overlap, get_twitch_streaming_line
    from core.wf_resolve import wf_invalidate_hub_snapshot

    platform = str(payload.get("platform") or "pc")
    guild_id = int(payload.get("guild_id") or 0)
    await wf_invalidate_hub_snapshot(platform)
    br, ar, cr, fr, sr, ir, sp, arb, nw = await _fetch_hub_data(platform)
    ia, bd = br
    if not bd and not ar and not cr:
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    wishlist = None
    if bd and ia and guild_id:
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
    hub_payload = {"platform": platform, "guild_id": guild_id}
    return await _edit_success(
        interaction,
        emb,
        panel_type="wf_hub",
        payload=hub_payload,
        view=_hub_view(platform, guild_id),
    )


async def retry_wf_status(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.status import build_status_embed

    platform = str(payload.get("platform") or "pc")
    await wf_invalidate_status_snapshot(platform)
    br, ar, cr, fr, sr, ir = await asyncio.gather(
        get_baro_status(),
        fetch_alerts(),
        get_all_cycles(),
        fetch_fissures(platform),
        fetch_sortie(),
        fetch_invasions(),
    )
    ia, bd = br
    if not bd and not ar and not cr and not fr and not sr:
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    emb = build_status_embed(
        ia, bd or {}, ar or [], cr or {}, fr or [], sr or {},
        interaction.client, ir or [], platform=platform,
    )
    status_payload = {"platform": platform}
    return await _edit_success(
        interaction, emb, panel_type="wf_status", payload=status_payload,
    )


async def retry_wf_sortie(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.sortie import SORTIE_CACHE_KEY, _build_embed
    from core.wf_resolve import wf_invalidate

    await wf_invalidate(SORTIE_CACHE_KEY)
    data = await fetch_sortie()
    if wf_fetch_failed(data):
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    emb = _build_embed(data, interaction.client)
    return await _edit_success(interaction, emb, panel_type="wf_sortie")


async def retry_wf_fissures(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.fissures import _build_embed

    platform = str(payload.get("platform") or "pc")
    tier_filter = str(payload.get("tier_filter") or "all")
    cache_key = f"warframe:fissures:{platform}"
    from core.wf_resolve import wf_invalidate

    await wf_invalidate(cache_key)
    data = await fetch_fissures(platform)
    if wf_fetch_failed(data):
        await interaction.followup.send(
            "Still can't load fissures. Try again in a bit.",
            ephemeral=True,
        )
        return False
    emb = _build_embed(data, interaction.client, tier_filter=tier_filter, cache_key=cache_key)
    fiss_payload = {"platform": platform, "tier_filter": tier_filter}
    return await _edit_success(
        interaction, emb, panel_type="wf_fissures", payload=fiss_payload,
    )


async def retry_wf_invasions(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.invasions import _build_invasions_embed
    from core.wf_resolve import wf_invalidate

    await wf_invalidate("warframe:invasions")
    data = await fetch_invasions()
    if wf_fetch_failed(data):
        await interaction.followup.send(
            "Invasions still won't load. Try again in a minute.",
            ephemeral=True,
        )
        return False
    faction_filter = payload.get("faction_filter") or None
    if faction_filter == "":
        faction_filter = None
    if faction_filter:
        fl = str(faction_filter).lower()
        data = [
            inv for inv in data
            if fl in str((inv.get("attacker") or {}).get("faction", "")).lower()
            or fl in str((inv.get("defender") or {}).get("faction", "")).lower()
        ]
    inv_payload = {"faction_filter": faction_filter or ""}
    emb = _build_invasions_embed(data, interaction.client, faction_filter=faction_filter)
    return await _edit_success(
        interaction, emb, panel_type="wf_invasions", payload=inv_payload,
    )


async def retry_wf_alerts(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.alerts import ALERTS_CACHE_KEY, build_alerts_embed
    from core.wf_resolve import wf_invalidate

    await wf_invalidate(ALERTS_CACHE_KEY)
    data = await fetch_alerts()
    if wf_fetch_failed(data):
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    emb = build_alerts_embed(data, interaction.client)
    return await _edit_success(interaction, emb, panel_type="wf_alerts")


async def retry_wf_daily_ops(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.daily_ops import _build_embed, _fetch_daily_ops
    from core.wf_resolve import wf_invalidate_daily_ops

    guild_id = payload.get("guild_id")
    user_id = int(payload.get("user_id") or interaction.user.id)
    (_sp, _arb, _nw), plat = await _fetch_daily_ops(guild_id, user_id)
    await wf_invalidate_daily_ops(plat)
    (sp, arb, nw), plat2 = await _fetch_daily_ops(guild_id, user_id)
    if wf_fetch_failed(sp) and wf_fetch_failed(arb) and wf_fetch_failed(nw):
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    emb = _build_embed(sp, arb, nw, interaction.client, platform=plat2)
    ops_payload = {"guild_id": guild_id, "user_id": user_id}
    return await _edit_success(
        interaction, emb, panel_type="wf_daily_ops", payload=ops_payload,
    )


async def retry_wf_baro(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    import aiosqlite
    from commands.warframe.baro import (
        _baro_view_for,
        _persist_inventory_hash,
        _resolve_baro_status,
        _resolve_mark_new,
        build_baro_embed,
    )
    from database import DB_PATH

    guild_id = payload.get("guild_id")
    new_active, new_data = await _resolve_baro_status(fresh=True)
    if not new_data:
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    if new_data and not new_active:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT arrival_time, departure_time, location, inventory_json "
                "FROM baro_visits ORDER BY id DESC LIMIT 1"
            )
            new_data["_last_visit"] = await cur.fetchone()
    mark = await _resolve_mark_new(guild_id, new_data.get("inventory", []) or [])
    emb = build_baro_embed(
        new_data, new_active, interaction.client, guild_id=guild_id, mark_new=mark,
    )
    view = _baro_view_for(
        guild_id=guild_id,
        is_active=new_active,
        baro_data=new_data,
        mark_new=mark,
        client=interaction.client,
    )
    baro_payload = {"guild_id": guild_id}
    ok = await _edit_success(
        interaction, emb, panel_type="wf_baro", payload=baro_payload, view=view,
    )
    if ok and guild_id:
        await _persist_inventory_hash(guild_id, new_data.get("inventory", []) or [])
    return ok


async def retry_wf_world_state(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.world_state import WorldStateBoardView, build_world_state_embed
    from core.wf_resolve import wf_invalidate

    await wf_invalidate("warframe:baro", "warframe:cycles")
    emb = await build_world_state_embed(interaction.client)
    view = WorldStateBoardView()
    if interaction.message:
        await interaction.message.edit(embed=emb, view=view)
        return True
    return False


async def retry_wf_cycles(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from core.cycles_live import build_cycle_fields as _build_cycle_fields
    from core.utils import EMBED_COLORS, obsidian_embed
    from core.wf_resolve import wf_cycles_split, wf_footer_with_freshness, wf_invalidate

    await wf_invalidate("warframe:cycles")
    data = await get_all_cycles()
    success, failed = wf_cycles_split(data)
    if not success:
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    fields = _build_cycle_fields(success)
    desc = "Partial data: " + ", ".join(failed) + " unavailable." if failed else ""
    emb = obsidian_embed(
        "🌍 Open World Cycles",
        desc or "",
        color=EMBED_COLORS["warframe"],
        fields=fields if fields else None,
        footer=wf_footer_with_freshness(
            "See also: /warframe baro, /warframe alerts • **Update data** refreshes",
            "warframe:cycles",
        ),
        client=interaction.client,
    )
    return await _edit_success(interaction, emb, panel_type="wf_cycles")


async def retry_wf_worth(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.world_state import refresh_worth_data

    emb = await refresh_worth_data(interaction.client)
    return await _edit_success(interaction, emb, panel_type="wf_worth")


async def retry_wf_duviri(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.duviri import build_duviri_embed
    from core.wf_resolve import wf_invalidate

    await wf_invalidate("warframe:duviri")
    data = await fetch_duviri_circuit()
    if not data:
        await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            ephemeral=True,
        )
        return False
    emb = build_duviri_embed(data, interaction.client, guild=interaction.guild)
    return await _edit_success(interaction, emb, panel_type="wf_duviri")


async def retry_trade_search(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from datetime import datetime, timezone

    from api.warframe_api import get_warframe_market_price, search_warframe_market_item
    from commands.trading.trade_price import _build_trade_embed, _trade_price_view
    from core.utils import error_embed

    item = str(payload.get("item") or "")
    platform = str(payload.get("platform") or "pc")
    item_data = await search_warframe_market_item(item, platform)
    if not item_data:
        await interaction.followup.send(
            embed=error_embed(
                "Item Not Found",
                f"Still can't find **{item}** on Warframe Market.",
                client=interaction.client,
            ),
            ephemeral=True,
        )
        return False
    item_url_name = item_data.get("url_name", "")
    price_data = await get_warframe_market_price(item_url_name, platform)
    if not price_data:
        await interaction.followup.send(
            embed=error_embed(
                "Price Data Unavailable",
                f"Found **{item_data.get('item_name', item)}** but prices won't load yet.",
                client=interaction.client,
            ),
            ephemeral=True,
        )
        return False
    emb = _build_trade_embed(
        item_data,
        price_data,
        platform,
        interaction.client,
        author=interaction.user,
        fetched_at=datetime.now(timezone.utc),
    )
    full_payload = {
        "runner_id": int(payload.get("owner_user_id") or interaction.user.id),
        "item_url_name": item_url_name,
        "platform": platform,
        "item_data": item_data,
    }
    market_url = f"https://warframe.market/items/{item_url_name}"
    view = _trade_price_view(full_payload, market_url)
    return await _edit_success(
        interaction, emb, panel_type="trade_price", payload=full_payload, view=view,
    )


async def retry_trade_price(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from datetime import datetime, timezone

    from api.warframe_api import get_warframe_market_price
    from commands.trading.trade_price import refresh_trade_price_panel

    payload = {
        **payload,
        "runner_id": int(payload.get("owner_user_id") or payload.get("runner_id") or interaction.user.id),
    }
    return await refresh_trade_price_panel(interaction, payload)


HANDLERS: dict[str, Any] = {
    "wf_hub": retry_wf_hub,
    "wf_status": retry_wf_status,
    "wf_sortie": retry_wf_sortie,
    "wf_fissures": retry_wf_fissures,
    "wf_invasions": retry_wf_invasions,
    "wf_alerts": retry_wf_alerts,
    "wf_daily_ops": retry_wf_daily_ops,
    "wf_baro": retry_wf_baro,
    "wf_world_state": retry_wf_world_state,
    "wf_cycles": retry_wf_cycles,
    "wf_worth": retry_wf_worth,
    "wf_duviri": retry_wf_duviri,
    "trade_search": retry_trade_search,
    "trade_price": retry_trade_price,
}
