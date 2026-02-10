"""Archon Hunt tracking command."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser  # type: ignore

from utils import obsidian_embed
from warframe_api import fetch_archon_hunt_data


def format_time_remaining(expiry_time: datetime) -> str:
    """Format time remaining until archon hunt expires."""
    now = datetime.now(timezone.utc)
    time_remaining = expiry_time - now
    
    if time_remaining.total_seconds() <= 0:
        return "Expired"
    
    total_seconds = int(time_remaining.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def setup(bot, group=None):
    """Register the archon command."""
    command_decorator = group.command(name="archon", description="View current Archon Hunt details.") if group else bot.tree.command(name="archon", description="View current Archon Hunt details.")
    
    @command_decorator
    async def archon(interaction: discord.Interaction):
        """Display current Archon Hunt information."""
        await interaction.response.defer(ephemeral=False)
        
        archon_data = await fetch_archon_hunt_data()
        
        if not archon_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Could not fetch Archon Hunt data from Warframe API. Please try again later.",
                    color=discord.Color.red(),
                    footer="warframestat.us",
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Extract archon hunt information
        boss = archon_data.get("boss", "Unknown")
        faction = archon_data.get("faction", "Unknown")
        missions = archon_data.get("missions", [])
        expiry = archon_data.get("expiry", "")
        
        # Map archon names to shard types
        archon_shards = {
            "Amar": "Crimson Archon Shard",
            "Nira": "Amber Archon Shard",
            "Boreal": "Azure Archon Shard"
        }
        
        shard_type = archon_shards.get(boss, "Unknown Shard")
        
        # Parse expiry time
        expiry_time = None
        time_str = "Unknown"
        try:
            expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            if expiry_time:
                time_str = format_time_remaining(expiry_time)
        except Exception:
            pass
        
        # Build mission list
        mission_list = ""
        if missions:
            for i, mission in enumerate(missions, 1):
                node = mission.get("node", "Unknown")
                mission_type = mission.get("type", "Unknown")
                mission_list += f"**{i}.** `{node}`\n{mission_type}\n\n"
        else:
            mission_list = "No mission data available."
        
        # Build fields
        fields = [
            ("⚔️ Archon", boss, True),
            ("💎 Reward", shard_type, True),
            ("🏛️ Faction", faction, True),
        ]
        
        if expiry_time:
            fields.append(("⏰ Time Remaining", f"{time_str}\n<t:{int(expiry_time.timestamp())}:R>", True))
        
        fields.append(("📍 Missions", mission_list.strip() or "No missions available.", False))
        
        # Determine color based on archon
        color_map = {
            "Amar": discord.Color.red(),
            "Nira": discord.Color.gold(),
            "Boreal": discord.Color.blue()
        }
        color = color_map.get(boss, discord.Color.purple())
        
        embed = obsidian_embed(
            "⚔️ Archon Hunt",
            "",
            color=color,
            fields=fields,
            footer="warframestat.us • Refreshes every 60s",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=False)
