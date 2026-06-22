"""Invasions tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from core.utils import obsidian_embed, warframe_data_unavailable_embed, BUTTON_ONLY_RUNNER_MSG, render_bar, error_embed
from core.wf_resolve import (
    wf_fetch_failed,
    wf_footer,
    wf_invalidate,
)
from api.warframe_api import fetch_invasions
from views import RefreshView
from core.refresh_panels import register_refresh_panel
from core.wf_retry_panels import send_wf_retry_message
import dateparser


def _build_invasions_embed(invasions_data, client, *, faction_filter: str | None = None):
    """Build the invasions embed. Used for initial display and refresh."""
    invasions_data = sorted(invasions_data, key=lambda x: x.get("completion", 0))
    now_utc = datetime.now(timezone.utc)
    fields = []
    for inv in invasions_data[:5]:
        node = inv.get("node") or inv.get("nodeKey", "Unknown Location")
        att_obj = inv.get("attacker") or {}
        def_obj = inv.get("defender") or {}
        attacker = att_obj.get("faction") or att_obj.get("factionKey", "Unknown")
        defender = def_obj.get("faction") or def_obj.get("factionKey", "Unknown")
        completion = inv.get("completion", 0)
        count = inv.get("count", 0)
        required_runs = inv.get("requiredRuns", 0)

        att_reward = att_obj.get("reward") or {}
        def_reward = def_obj.get("reward") or {}
        att_counted = att_reward.get("countedItems", [])
        def_counted = def_reward.get("countedItems", [])

        attacker_reward_str = "None"
        if att_counted:
            items = [item.get("type") or item.get("key", "?") for item in att_counted]
            attacker_reward_str = ", ".join(items[:2]) + (f" +{len(items) - 2}" if len(items) > 2 else "")

        defender_reward_str = "None"
        if def_counted:
            items = [item.get("type") or item.get("key", "?") for item in def_counted]
            defender_reward_str = ", ".join(items[:2]) + (f" +{len(items) - 2}" if len(items) > 2 else "")

        pct = max(0, min(100, float(completion)))

        time_str = "—"
        activation = inv.get("activation")
        if activation:
            try:
                act_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if act_time:
                    act_utc = act_time.replace(tzinfo=timezone.utc) if act_time.tzinfo is None else act_time
                    elapsed = now_utc - act_utc
                    total_sec = max(0, int(elapsed.total_seconds()))
                    hours = total_sec // 3600
                    minutes = (total_sec % 3600) // 60
                    time_str = f"{hours}h {minutes}m active"
            except Exception:
                pass

        value = f"**{attacker}** ⚔️ **{defender}**\n"
        value += f"{render_bar(pct, length=10)}\n"
        value += f"⏱️ {time_str}\n"
        if required_runs:
            value += f"Runs: {count:,}/{required_runs:,}\n"
        value += f"\n**{attacker}:** {attacker_reward_str}\n"
        value += f"**{defender}:** {defender_reward_str}"

        fields.append((f"📍 {node}", value, False))

    desc = f"**{len(invasions_data)} Active Invasion{'s' if len(invasions_data) != 1 else ''}**"
    if faction_filter:
        desc = f"_Filter: **{faction_filter}** — `/preferences invasion_faction` to change_\n\n{desc}"
    if len(invasions_data) > 5:
        desc += f"\n_Showing 5 of {len(invasions_data)} invasions_"

    from core.wf_resolve import wf_footer

    return obsidian_embed(
        "⚔️ Active Invasions",
        f"> {desc}",
        category="warframe",
        fields=fields,
        footer=wf_footer("warframestat.us · Refreshes every 60s", "warframe:invasions"),
        client=client,
    )


def setup(bot, group=None):
    """Register the invasions command."""
    command_decorator = group.command(name="invasions", description="View active faction invasions with rewards.") if group else bot.tree.command(name="invasions", description="View active faction invasions with rewards.")

    @command_decorator
    async def invasions(interaction: discord.Interaction):
        """Display all active invasions."""
        await interaction.response.defer(ephemeral=False)

        invasions_data = await fetch_invasions()
        faction_filter = None
        if interaction.guild:
            from core.user_prefs import default_invasion_faction

            faction_filter = await default_invasion_faction(
                interaction.guild.id, interaction.user.id
            )

        if wf_fetch_failed(invasions_data):
            inv_payload = {"faction_filter": faction_filter or ""}
            return await send_wf_retry_message(
                interaction,
                embed=warframe_data_unavailable_embed(interaction.client),
                retry_type="wf_invasions",
                payload=inv_payload,
                owner_user_id=interaction.user.id,
                fetch_probe=fetch_invasions,
                edit=False,
            )

        if not invasions_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Active Invasions",
                    "No active invasions at this time. Check back later!",
                    category="warframe",
                    footer=wf_footer("warframestat.us", "warframe:invasions"),
                    client=interaction.client,
                ),
            )

        if faction_filter:
            fl = faction_filter.lower()
            invasions_data = [
                inv for inv in invasions_data
                if fl in str((inv.get("attacker") or {}).get("faction", "")).lower()
                or fl in str((inv.get("defender") or {}).get("faction", "")).lower()
            ]
            if not invasions_data:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "⚔️ Active Invasions",
                        f"No invasions matching **{faction_filter}** right now.\n\n"
                        "Try another faction or clear the preset in **`/preferences invasion_faction`**.",
                        category="warframe",
                        client=interaction.client,
                    ),
                )

        embed = _build_invasions_embed(invasions_data, interaction.client, faction_filter=faction_filter)
        payload = {"faction_filter": faction_filter or ""}
        view = RefreshView.panel("wf_invasions", payload=payload)
        msg = await interaction.followup.send(embed=embed, view=view)
        await register_refresh_panel(msg, "wf_invasions", payload)
