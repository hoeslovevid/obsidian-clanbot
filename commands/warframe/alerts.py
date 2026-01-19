"""Alerts command and notification system."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser  # type: ignore

from utils import obsidian_embed
from warframe_api import fetch_alerts


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
        
        if not alerts_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Failed to fetch alerts data. Please try again later.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        if not alerts_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📢 Active Alerts",
                    "No active alerts at this time.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                )
            )
        
        # Build description
        desc = f"**Active Alerts:** {len(alerts_data)}\n\n"
        
        for i, alert in enumerate(alerts_data[:10], 1):  # Limit to 10 alerts
            mission = alert.get("mission", {})
            mission_type = mission.get("missionType", "Unknown")
            node = mission.get("node", "Unknown")
            faction = mission.get("faction", "Unknown")
            expiry = alert.get("expiry", "")
            time_remaining = format_time_remaining(expiry)
            rewards = format_alert_rewards(alert)
            
            desc += f"**{i}. {node}** ({mission_type})\n"
            desc += f"• Faction: {faction}\n"
            desc += f"• Rewards: {rewards}\n"
            desc += f"• Time Remaining: {time_remaining}\n\n"
        
        if len(alerts_data) > 10:
            desc += f"_...and {len(alerts_data) - 10} more alerts_"
        
        embed = obsidian_embed(
            "📢 Active Alerts",
            desc,
            color=discord.Color.blue(),
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed)
