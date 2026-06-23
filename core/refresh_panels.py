"""Persistent **Update data** panels — DB-backed routing survives bot restarts."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import aiosqlite  # type: ignore
import discord  # type: ignore
from discord import ui  # type: ignore

from database import DB_PATH

logger = logging.getLogger(__name__)

REFRESH_CUSTOM_ID = "obsidian:refresh"

PanelHandler = Callable[[discord.Interaction, dict[str, Any]], Awaitable[bool]]

# Prevents double-handling when PersistentRefreshView and component_handler both route
# the same click (the handler used to await message.edit before defer, opening a race).
_refresh_claims: set[int] = set()


def _try_claim_component(interaction_id: int) -> bool:
    if interaction_id in _refresh_claims:
        return False
    _refresh_claims.add(interaction_id)
    return True


def _release_component(interaction_id: int) -> None:
    _refresh_claims.discard(interaction_id)


async def defer_component_interaction(interaction: discord.Interaction) -> bool:
    """Claim and defer immediately. Returns False if already handled."""
    if not _try_claim_component(interaction.id):
        return False
    try:
        if interaction.response.is_done():
            return True
        try:
            await interaction.response.defer()
        except (discord.InteractionResponded, discord.HTTPException) as exc:
            code = getattr(exc, "code", None)
            if code == 40060 or isinstance(exc, discord.InteractionResponded):
                _release_component(interaction.id)
                return False
            raise
        return True
    except Exception:
        _release_component(interaction.id)
        raise


async def ensure_refresh_panel_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_panel_meta (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                panel_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, message_id)
            )
            """
        )
        await db.commit()


async def register_refresh_panel(
    message: discord.Message,
    panel_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    if not message.guild:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO refresh_panel_meta
            (guild_id, channel_id, message_id, panel_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message.guild.id,
                message.channel.id,
                message.id,
                panel_type,
                json.dumps(payload or {}),
                now,
            ),
        )
        await db.commit()


async def unregister_refresh_panel(message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM refresh_panel_meta WHERE message_id=?",
            (message_id,),
        )
        await db.commit()


async def get_refresh_panel(message_id: int) -> Optional[tuple[str, dict[str, Any]]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT panel_type, payload_json FROM refresh_panel_meta
            WHERE message_id=? LIMIT 1
            """,
            (message_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[1] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return str(row[0]), payload


async def refresh_followup_ephemeral(
    interaction: discord.Interaction,
    content: str,
    *,
    embed: discord.Embed | None = None,
) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(content=content, embed=embed, ephemeral=True)
    except (discord.HTTPException, discord.InteractionResponded):
        pass


async def refresh_edit_message(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    content: str | None = None,
    panel_type: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Edit the panel message after RefreshView / persistent handler deferred."""
    if interaction.message:
        await interaction.message.edit(content=content, embed=embed, view=view)
    else:
        await interaction.edit_original_response(content=content, embed=embed, view=view)
    if interaction.message and panel_type:
        await register_refresh_panel(interaction.message, panel_type, payload or {})


async def reenable_message_view(interaction: discord.Interaction, view: discord.ui.View) -> None:
    for child in view.children:
        child.disabled = False
    try:
        if interaction.message:
            await interaction.message.edit(view=view)
    except Exception:
        pass


async def runner_only(
    interaction: discord.Interaction,
    payload: dict[str, Any],
    message: str,
) -> bool:
    runner_id = int(payload.get("runner_id") or 0)
    if runner_id and interaction.user.id != runner_id:
        await refresh_followup_ephemeral(interaction, message)
        return False
    return True


# ---------------------------------------------------------------------------
# Panel handlers (lazy imports to avoid cycles)
# ---------------------------------------------------------------------------


async def _refresh_wf_archon(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.archon import refresh_archon_panel

    return await refresh_archon_panel(interaction)


async def _refresh_wf_sortie(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from api.warframe_api import fetch_sortie
    from commands.warframe.sortie import _build_embed
    from core.wf_resolve import SORTIE_CACHE_KEY, wf_fetch_failed, wf_invalidate
    from views._core import RefreshView

    await wf_invalidate(SORTIE_CACHE_KEY)
    data = await fetch_sortie()
    if wf_fetch_failed(data):
        await refresh_followup_ephemeral(
            interaction,
            "Couldn't refresh the sortie yet — try **Update data** again soon.",
        )
        return False
    emb = _build_embed(data, interaction.client)
    view = RefreshView.panel("wf_sortie")
    await refresh_edit_message(interaction, embed=emb, view=view, panel_type="wf_sortie")
    return True


async def _refresh_wf_alerts(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from api.warframe_api import fetch_alerts
    from commands.warframe.alerts import ALERTS_CACHE_KEY, format_alert_rewards, format_time_remaining
    from core.utils import obsidian_embed
    from core.wf_resolve import wf_fetch_failed, wf_footer, wf_invalidate
    from views._core import RefreshView

    await wf_invalidate(ALERTS_CACHE_KEY)
    new_data = await fetch_alerts()
    if wf_fetch_failed(new_data):
        await refresh_followup_ephemeral(
            interaction,
            "Couldn't refresh yet — the stats service is still having trouble. Try again soon.",
        )
        return False

    def _build(data):
        if not data:
            return obsidian_embed(
                "📢 Active Alerts",
                "No active alerts at this time.",
                category="warning",
                footer=wf_footer("warframestat.us · Refreshes every 60s", ALERTS_CACHE_KEY),
                client=interaction.client,
            )
        d = f"> **{len(data)} active alert{'s' if len(data) != 1 else ''}**\n\n"
        for i, alert in enumerate(data[:10], 1):
            mission = alert.get("mission", {})
            d += (
                f"**{i}. {mission.get('node', '?')}** ({mission.get('missionType', '?')})\n"
                f"• Faction: {mission.get('faction', '?')} · Rewards: {format_alert_rewards(alert)}\n"
                f"-# Ends: {format_time_remaining(alert.get('expiry', ''))}\n\n"
            )
        if len(data) > 10:
            d += f"_...and {len(data) - 10} more_"
        return obsidian_embed(
            "📢 Active Alerts",
            d,
            category="warframe",
            footer=wf_footer("warframestat.us · Refreshes every 60s", ALERTS_CACHE_KEY),
            client=interaction.client,
        )

    emb = _build(new_data)
    view = RefreshView.panel("wf_alerts")
    await refresh_edit_message(interaction, embed=emb, view=view, panel_type="wf_alerts")
    return True


async def _refresh_wf_invasions(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from api.warframe_api import fetch_invasions
    from commands.warframe.invasions import _build_invasions_embed
    from core.wf_resolve import wf_fetch_failed, wf_invalidate
    from views._core import RefreshView

    await wf_invalidate("warframe:invasions")
    new_data = await fetch_invasions()
    if wf_fetch_failed(new_data):
        await refresh_followup_ephemeral(
            interaction,
            "The stats API is still busy — try again in a minute.",
        )
        return False
    faction_filter = payload.get("faction_filter") or None
    if faction_filter == "":
        faction_filter = None
    if not faction_filter and interaction.guild:
        from core.user_prefs import default_invasion_faction

        faction_filter = await default_invasion_faction(
            interaction.guild.id, interaction.user.id,
        )
    if faction_filter:
        fl = str(faction_filter).lower()
        new_data = [
            inv for inv in new_data
            if fl in str((inv.get("attacker") or {}).get("faction", "")).lower()
            or fl in str((inv.get("defender") or {}).get("faction", "")).lower()
        ]
    emb = _build_invasions_embed(new_data, interaction.client, faction_filter=faction_filter)
    view = RefreshView.panel("wf_invasions", payload=payload)
    await refresh_edit_message(interaction, embed=emb, view=view, panel_type="wf_invasions", payload=payload)
    return True


async def _refresh_wf_cycles(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from api.warframe_api import get_all_cycles
    from core.cycles_live import build_cycle_fields as _build_cycle_fields
    from core.utils import EMBED_COLORS, obsidian_embed
    from core.wf_resolve import wf_cycles_split, wf_footer_with_freshness, wf_invalidate
    from views._core import RefreshView

    await wf_invalidate("warframe:cycles")
    new_data = await get_all_cycles()
    new_success, new_failed = wf_cycles_split(new_data)
    if not new_success:
        await refresh_followup_ephemeral(
            interaction,
            "Couldn't refresh cycles yet — try again in a moment.",
        )
        return False
    new_fields = _build_cycle_fields(new_success)
    partial = [k for k in ("cetus", "vallis", "cambion") if k not in new_success]
    new_desc = "Partial data: " + ", ".join(partial) + " unavailable." if partial else ""
    new_emb = obsidian_embed(
        "🌍 Open World Cycles",
        new_desc or "",
        color=EMBED_COLORS["warframe"],
        fields=new_fields,
        footer=wf_footer_with_freshness(
            "See also: /warframe baro, /warframe alerts • **Update data** refreshes",
            "warframe:cycles",
        ),
        client=interaction.client,
    )
    view = RefreshView.panel("wf_cycles")
    await refresh_edit_message(interaction, embed=new_emb, view=view, panel_type="wf_cycles")
    return True


async def _refresh_wf_fissures(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from api.warframe_api import fetch_fissures
    from commands.warframe.fissures import _build_embed
    from core.wf_resolve import wf_fetch_failed, wf_invalidate
    from views._core import RefreshView

    platform = payload.get("platform", "pc")
    tier_filter = payload.get("tier_filter", "all")
    cache_key = f"warframe:fissures:{platform}"
    await wf_invalidate(cache_key)
    data = await fetch_fissures(platform)
    if wf_fetch_failed(data):
        await refresh_followup_ephemeral(
            interaction,
            "Couldn't refresh fissures yet — stats API is still having issues.",
        )
        return False
    emb = _build_embed(data, interaction.client, tier_filter=tier_filter, cache_key=cache_key)
    view = RefreshView.panel("wf_fissures", payload=payload)
    await refresh_edit_message(
        interaction, embed=emb, view=view, panel_type="wf_fissures", payload=payload,
    )
    return True


async def _refresh_wf_daily_ops(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.daily_ops import _build_embed, _fetch_daily_ops
    from core.wf_resolve import wf_invalidate_daily_ops
    from views._core import RefreshView

    guild_id = payload.get("guild_id")
    user_id = int(payload.get("user_id") or interaction.user.id)
    (_sp, _arb, _nw), plat = await _fetch_daily_ops(guild_id, user_id)
    await wf_invalidate_daily_ops(plat)
    (sp2, arb2, nw2), plat2 = await _fetch_daily_ops(guild_id, user_id)
    emb = _build_embed(sp2, arb2, nw2, interaction.client, platform=plat2)
    panel_payload = {"guild_id": guild_id, "user_id": user_id}
    view = RefreshView.panel("wf_daily_ops", payload=panel_payload)
    await refresh_edit_message(
        interaction, embed=emb, view=view, panel_type="wf_daily_ops", payload=panel_payload,
    )
    return True


async def _refresh_wf_status(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.status import refresh_status_data
    from views._core import RefreshView

    platform = payload.get("platform", "pc")
    new_emb = await refresh_status_data(interaction.client, platform)
    status_payload = {"platform": platform}
    view = RefreshView.panel("wf_status", payload=status_payload)
    await refresh_edit_message(
        interaction, embed=new_emb, view=view, panel_type="wf_status", payload=status_payload,
    )
    return True


async def _refresh_wf_worth(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.world_state import refresh_worth_data
    from views._core import RefreshView

    new_emb = await refresh_worth_data(interaction.client)
    view = RefreshView.panel("wf_worth")
    await refresh_edit_message(interaction, embed=new_emb, view=view, panel_type="wf_worth")
    return True


async def _refresh_wf_duviri(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from api.warframe_api import fetch_duviri_circuit
    from commands.warframe.duviri import build_duviri_embed
    from core.cache_utils import invalidate
    from views._core import RefreshView

    invalidate("warframe:duviri")
    data = await fetch_duviri_circuit()
    if not data:
        await refresh_followup_ephemeral(
            interaction,
            "Couldn't refresh Duviri data yet — try **Update data** again soon.",
        )
        return False
    new_emb = build_duviri_embed(data, interaction.client, guild=interaction.guild)
    view = RefreshView.panel("wf_duviri")
    await refresh_edit_message(interaction, embed=new_emb, view=view, panel_type="wf_duviri")
    return True


async def _refresh_wf_hub(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.hub import refresh_hub_panel

    return await refresh_hub_panel(interaction, payload)


async def _refresh_wf_baro(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.warframe.baro import refresh_baro_panel

    guild_id = payload.get("guild_id")
    return await refresh_baro_panel(interaction, guild_id)


async def _refresh_wf_cycle_live(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from api.warframe_api import get_all_cycles
    from core.cache_utils import invalidate
    from core.cycles_live import build_cycles_live_embed
    from views._core import RefreshView

    invalidate("warframe:cycles")
    fresh = await get_all_cycles()
    if not any(v for v in (fresh or {}).values()):
        await refresh_followup_ephemeral(
            interaction,
            "Couldn't refresh cycles yet — stats API returned no data. Try again soon.",
        )
        return False
    new_emb = build_cycles_live_embed(interaction.client, fresh or {})
    view = RefreshView.panel("wf_cycle_live", timeout=None)
    await refresh_edit_message(interaction, embed=new_emb, view=view, panel_type="wf_cycle_live")
    return True


async def _refresh_eco_wallet(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    if not await runner_only(interaction, payload, "Only the person who opened this wallet can refresh it."):
        return False
    from commands.economy.wallet import refresh_wallet_panel

    return await refresh_wallet_panel(interaction, payload)


async def _refresh_eco_leaderboard(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from core.utils import BUTTON_ONLY_RUNNER_MSG

    if not await runner_only(interaction, payload, BUTTON_ONLY_RUNNER_MSG):
        return False
    from commands.economy.leaderboard import refresh_leaderboard_panel

    return await refresh_leaderboard_panel(interaction, payload)


async def _refresh_trade_price(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from core.utils import BUTTON_ONLY_RUNNER_MSG

    if not await runner_only(interaction, payload, BUTTON_ONLY_RUNNER_MSG):
        return False
    from commands.trading.trade_price import refresh_trade_price_panel

    return await refresh_trade_price_panel(interaction, payload)


async def _refresh_clan_hq(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from core.action_panel_views import clan_hq_panel_view
    from core.clan_hq import build_clan_hq_embed
    from views._core import RefreshView

    if not interaction.guild:
        return False
    user_id = int(payload.get("user_id") or interaction.user.id)
    viewer = interaction.guild.get_member(user_id) or interaction.user
    embed = await build_clan_hq_embed(
        interaction.guild,
        client=interaction.client,
        user_id=user_id,
        viewer=viewer if isinstance(viewer, discord.Member) else None,
    )
    view = clan_hq_panel_view(guild_id=interaction.guild.id, user_id=user_id)
    await refresh_edit_message(
        interaction, embed=embed, view=view, panel_type="clan_hq", payload=payload,
    )
    return True


async def _refresh_notifications(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from core.action_panel_views import notifications_panel_view
    from core.notifications_hub import build_notifications_status_embed
    from views._core import RefreshView

    if not interaction.guild:
        return False
    user_id = int(payload.get("user_id") or interaction.user.id)
    member = interaction.guild.get_member(user_id) or interaction.user
    embed = await build_notifications_status_embed(
        interaction.guild, member, client=interaction.client,
    )
    view = notifications_panel_view(guild_id=interaction.guild.id, user_id=user_id)
    await refresh_edit_message(
        interaction, embed=embed, view=view, panel_type="notifications", payload=payload,
    )
    return True


async def _refresh_today(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.general.today import refresh_today_panel

    return await refresh_today_panel(interaction)


async def _refresh_claim_hub(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.economy.claim import refresh_claim_panel

    return await refresh_claim_panel(interaction)


async def _refresh_mod_inbox(interaction: discord.Interaction, payload: dict[str, Any]) -> bool:
    from commands.moderation.dashboard import refresh_mod_inbox_panel

    return await refresh_mod_inbox_panel(interaction)


PANEL_HANDLERS: dict[str, PanelHandler] = {
    "wf_archon": _refresh_wf_archon,
    "wf_sortie": _refresh_wf_sortie,
    "wf_alerts": _refresh_wf_alerts,
    "wf_invasions": _refresh_wf_invasions,
    "wf_cycles": _refresh_wf_cycles,
    "wf_fissures": _refresh_wf_fissures,
    "wf_daily_ops": _refresh_wf_daily_ops,
    "wf_status": _refresh_wf_status,
    "wf_worth": _refresh_wf_worth,
    "wf_duviri": _refresh_wf_duviri,
    "wf_hub": _refresh_wf_hub,
    "wf_baro": _refresh_wf_baro,
    "wf_cycle_live": _refresh_wf_cycle_live,
    "eco_wallet": _refresh_eco_wallet,
    "eco_leaderboard": _refresh_eco_leaderboard,
    "trade_price": _refresh_trade_price,
    "clan_hq": _refresh_clan_hq,
    "notifications": _refresh_notifications,
    "today": _refresh_today,
    "claim_hub": _refresh_claim_hub,
    "mod_inbox": _refresh_mod_inbox,
}


async def handle_refresh_button(
    bot: discord.Client,
    interaction: discord.Interaction,
    *,
    view: Optional[discord.ui.View] = None,
) -> None:
    """Defer, dispatch panel refresh, recover on failure."""
    if not await defer_component_interaction(interaction):
        return

    try:
        message = interaction.message
        if not message:
            await refresh_followup_ephemeral(
                interaction,
                "This refresh button is no longer attached to a message.",
            )
            return

        active_view = view
        if active_view is None and message.components:
            try:
                active_view = discord.ui.View.from_message(message)
            except Exception:
                active_view = None

        if active_view:
            for child in active_view.children:
                child.disabled = True
            try:
                await message.edit(view=active_view)
            except Exception:
                pass

        meta = await get_refresh_panel(message.id)
        if not meta:
            await refresh_followup_ephemeral(
                interaction,
                "This panel expired — run the command again for a fresh board.",
            )
            if active_view:
                await reenable_message_view(interaction, active_view)
            return

        panel_type, payload = meta
        handler = PANEL_HANDLERS.get(panel_type)
        if not handler:
            logger.warning("[refresh] unknown panel_type=%s message=%s", panel_type, message.id)
            await refresh_followup_ephemeral(
                interaction,
                "This panel type is no longer supported — run the command again.",
            )
            if active_view:
                await reenable_message_view(interaction, active_view)
            return

        try:
            ok = await handler(interaction, payload)
            if not ok and active_view:
                await reenable_message_view(interaction, active_view)
        except discord.InteractionResponded:
            logger.debug("[refresh] double-respond panel=%s", panel_type)
            await refresh_followup_ephemeral(
                interaction,
                "Couldn't refresh — try **Update data** again.",
            )
            if active_view:
                await reenable_message_view(interaction, active_view)
        except discord.NotFound:
            await refresh_followup_ephemeral(
                interaction,
                "This message was deleted — run the command again.",
            )
        except discord.Forbidden:
            await refresh_followup_ephemeral(
                interaction,
                "I can't update this message anymore (missing channel access). Run the command again.",
            )
        except discord.HTTPException as exc:
            logger.debug("[refresh] edit failed panel=%s: %s", panel_type, exc)
            await refresh_followup_ephemeral(
                interaction,
                "Couldn't refresh — try again in a moment.",
            )
            if active_view:
                await reenable_message_view(interaction, active_view)
        except Exception:
            logger.exception("[refresh] panel=%s message=%s", panel_type, message.id)
            await refresh_followup_ephemeral(
                interaction,
                "Something went wrong refreshing this panel — try again or re-run the command.",
            )
            if active_view:
                await reenable_message_view(interaction, active_view)
    finally:
        _release_component(interaction.id)


class PersistentRefreshView(ui.View):
    """Legacy add_view hook — refresh is routed via ``component_handler`` only.

    Do not ``bot.add_view()`` this class; pairing it with ``on_interaction`` routing
    for the same ``custom_id`` causes error 40060 (double acknowledge).
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Update data",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id=REFRESH_CUSTOM_ID,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: ui.Button,
    ) -> None:
        if button.disabled:
            from core.interaction_recovery import reply_expired_panel

            if not interaction.response.is_done():
                await reply_expired_panel(interaction, title="Panel expired")
            else:
                await refresh_followup_ephemeral(
                    interaction,
                    "This panel expired — run the command again.",
                )
            return
        await handle_refresh_button(interaction.client, interaction)


async def send_refresh_panel(
    message: discord.Message,
    panel_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Register panel metadata after the message is sent."""
    await register_refresh_panel(message, panel_type, payload)
