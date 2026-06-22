"""Alerts command and notification system."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser  # type: ignore

from core.utils import obsidian_embed, warframe_data_unavailable_embed
from core.wf_resolve import (
    wf_fetch_failed,
    wf_footer,
    wf_invalidate,
    wf_retry_denied,
    wf_retry_guard,
)
from api.warframe_api import fetch_alerts
from views import RetryView, RefreshView
from core.refresh_panels import register_refresh_panel

ALERTS_CACHE_KEY = "warframe:alerts"


def format_alert_rewards(alert: dict) -> str:
    """Format alert rewards into a readable string."""
    rewards = []
    if alert.get("mission", {}).get("reward"):
        reward = alert["mission"]["reward"]
        if reward.get("items"):
            rewards.extend(reward["items"])
        if reward.get("countedItems"):
            for item in reward["countedItems"]:
                count = item.get("count", 1)
                name = item.get("ItemType", "Unknown")
                rewards.append(f"{count}x {name}")
    
    if rewards:
        return ", ".join(rewards)
    return "Unknown rewards"


def format_time_remaining(expiry_str: str) -> str:
    """Format time remaining until expiry."""
    try:
        expiry = dateparser.parse(expiry_str, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        if not expiry:
            return "Unknown"
        
        now = datetime.now(timezone.utc)
        delta = expiry - now
        
        if delta.total_seconds() <= 0:
            return "Expired"
        
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except Exception:
        return "Unknown"


def setup(bot, group=None):
    """Register the alerts command."""
    
    command_decorator = group.command(name="alerts", description="View active Warframe alerts.") if group else bot.tree.command(name="alerts", description="View active Warframe alerts.")
    
    @command_decorator
    async def alerts(interaction: discord.Interaction):
        """Display active alerts."""
        await interaction.response.defer()
        
        alerts_data = await fetch_alerts()

        if wf_fetch_failed(alerts_data):
            async def on_retry(btn_interaction: discord.Interaction):
                if not wf_retry_guard(btn_interaction, interaction.user.id):
                    return await wf_retry_denied(btn_interaction)
                await btn_interaction.response.defer()
                new_data = await fetch_alerts()
                if wf_fetch_failed(new_data):
                    return await btn_interaction.followup.send(
                        "Still can't reach the stats server. Give it another minute or try **Try again** again.",
                        ephemeral=True,
                    )
                if not new_data:
                    emb = obsidian_embed("📢 Active Alerts", "No active alerts at this time.", category="warning", client=interaction.client)
                else:
                    desc = f"**Active Alerts:** {len(new_data)}\n\n"
                    for i, alert in enumerate(new_data[:10], 1):
                        mission = alert.get("mission", {})
                        desc += f"**{i}. {mission.get('node', '?')}** ({mission.get('missionType', '?')})\n• Faction: {mission.get('faction', '?')}\n• Rewards: {format_alert_rewards(alert)}\n• Time: {format_time_remaining(alert.get('expiry', ''))}\n\n"
                    if len(new_data) > 10:
                        desc += f"_...and {len(new_data) - 10} more_"
                    emb = obsidian_embed(
                        "📢 Active Alerts",
                        desc,
                        category="warframe",
                        footer=wf_footer(f"{len(new_data)} active · warframestat.us", ALERTS_CACHE_KEY),
                        client=interaction.client,
                    )
                await btn_interaction.message.edit(embed=emb, view=None)

            from core.wf_recovery import attach_notify_when_back
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=attach_notify_when_back(RetryView(on_retry)),
            )

        if not alerts_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📢 Active Alerts",
                    "No active alerts at this time.",
                    category="warning",
                    client=interaction.client,
                )
            )

        # Build description
        desc = f"> **{len(alerts_data)} active alert{'s' if len(alerts_data) != 1 else ''}**\n\n"

        for i, alert in enumerate(alerts_data[:10], 1):
            mission = alert.get("mission", {})
            mission_type = mission.get("missionType", "Unknown")
            node = mission.get("node", "Unknown")
            faction = mission.get("faction", "Unknown")
            expiry = alert.get("expiry", "")
            time_remaining = format_time_remaining(expiry)
            rewards = format_alert_rewards(alert)

            desc += f"**{i}. {node}** ({mission_type})\n"
            desc += f"• Faction: {faction} · Rewards: {rewards}\n"
            desc += f"-# Ends: {time_remaining}\n\n"

        if len(alerts_data) > 10:
            desc += f"_...and {len(alerts_data) - 10} more alerts_"

        def _build_alerts_embed(data):
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
                d += f"**{i}. {mission.get('node', '?')}** ({mission.get('missionType', '?')})\n• Faction: {mission.get('faction', '?')} · Rewards: {format_alert_rewards(alert)}\n-# Ends: {format_time_remaining(alert.get('expiry', ''))}\n\n"
            if len(data) > 10:
                d += f"_...and {len(data) - 10} more_"
            return obsidian_embed(
                "📢 Active Alerts",
                d,
                category="warframe",
                footer=wf_footer("warframestat.us · Refreshes every 60s", ALERTS_CACHE_KEY),
                client=interaction.client,
            )

        embed = obsidian_embed(
            "📢 Active Alerts",
            desc,
            category="warframe",
            thumbnail=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None,
            footer=wf_footer(f"{len(alerts_data)} active · warframestat.us", ALERTS_CACHE_KEY),
            client=interaction.client,
        )
        view = RefreshView.panel("wf_alerts")
        msg = await interaction.followup.send(embed=embed, view=view)
        await register_refresh_panel(msg, "wf_alerts", {})
