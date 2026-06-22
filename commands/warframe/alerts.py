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
)
from api.warframe_api import fetch_alerts
from views import RefreshView
from core.refresh_panels import register_refresh_panel
from core.wf_retry_panels import send_wf_retry_message

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


def build_alerts_embed(alerts_data, client) -> discord.Embed:
    """Build alerts embed (shared by command + retry handler)."""
    if not alerts_data:
        return obsidian_embed(
            "📢 Active Alerts",
            "No active alerts at this time.",
            category="warning",
            footer=wf_footer("warframestat.us · Refreshes every 60s", ALERTS_CACHE_KEY),
            client=client,
        )
    desc = f"> **{len(alerts_data)} active alert{'s' if len(alerts_data) != 1 else ''}**\n\n"
    for i, alert in enumerate(alerts_data[:10], 1):
        mission = alert.get("mission", {})
        desc += (
            f"**{i}. {mission.get('node', '?')}** ({mission.get('missionType', '?')})\n"
            f"• Faction: {mission.get('faction', '?')} · Rewards: {format_alert_rewards(alert)}\n"
            f"-# Ends: {format_time_remaining(alert.get('expiry', ''))}\n\n"
        )
    if len(alerts_data) > 10:
        desc += f"_...and {len(alerts_data) - 10} more alerts_"
    return obsidian_embed(
        "📢 Active Alerts",
        desc,
        category="warframe",
        footer=wf_footer(f"{len(alerts_data)} active · warframestat.us", ALERTS_CACHE_KEY),
        client=client,
    )


def setup(bot, group=None):
    """Register the alerts command."""
    
    command_decorator = group.command(name="alerts", description="View active Warframe alerts.") if group else bot.tree.command(name="alerts", description="View active Warframe alerts.")
    
    @command_decorator
    async def alerts(interaction: discord.Interaction):
        """Display active alerts."""
        await interaction.response.defer()
        
        alerts_data = await fetch_alerts()

        if wf_fetch_failed(alerts_data):
            return await send_wf_retry_message(
                interaction,
                embed=warframe_data_unavailable_embed(interaction.client),
                retry_type="wf_alerts",
                payload={},
                owner_user_id=interaction.user.id,
                fetch_probe=fetch_alerts,
                edit=False,
            )

        if not alerts_data:
            return await interaction.followup.send(
                embed=build_alerts_embed([], interaction.client),
            )

        embed = build_alerts_embed(alerts_data, interaction.client)
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        view = RefreshView.panel("wf_alerts")
        msg = await interaction.followup.send(embed=embed, view=view)
        await register_refresh_panel(msg, "wf_alerts", {})
