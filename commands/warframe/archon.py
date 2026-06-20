"""Archon Hunt tracking command."""
import time
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser  # type: ignore

from core.utils import obsidian_embed, warframe_data_unavailable_embed
from api.warframe_api import fetch_archon_hunt_data
from views import RefreshView

# Per-user refresh cooldown (Item 15) — guards the warframestat.us API from abuse
# when many users mash the refresh button on a single embed.
_REFRESH_COOLDOWN_SECONDS = 30
_last_refresh: dict[int, float] = {}


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


def build_archon_embed(archon_data: dict, client=None) -> discord.Embed:
    """Build the Archon Hunt embed from raw API data (extracted for reuse by RefreshView)."""
    boss = archon_data.get("boss", "Unknown")
    faction = archon_data.get("faction", "Unknown")
    missions = archon_data.get("missions", [])
    expiry = archon_data.get("expiry", "")

    archon_shards = {
        "Amar":   "Crimson Archon Shard",
        "Nira":   "Amber Archon Shard",
        "Boreal": "Azure Archon Shard",
    }
    shard_type = archon_shards.get(boss, "Unknown Shard")

    expiry_time = None
    time_str = "Unknown"
    try:
        expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        if expiry_time:
            time_str = format_time_remaining(expiry_time)
    except Exception:
        pass

    mission_list = ""
    if missions:
        for i, mission in enumerate(missions, 1):
            node = mission.get("node", "Unknown")
            mission_type = mission.get("type", "Unknown")
            mission_list += f"**{i}.** `{node}`\n{mission_type}\n\n"
    else:
        mission_list = "No mission data available."

    fields = [
        ("⚔️ Archon", boss, True),
        ("💎 Reward", shard_type, True),
        ("🏛️ Faction", faction, True),
    ]
    if expiry_time:
        fields.append(("⏰ Time Remaining", f"{time_str}\n<t:{int(expiry_time.timestamp())}:R>", True))
    fields.append(("📍 Missions", mission_list.strip() or "No missions available.", False))

    color_map = {
        "Amar":   discord.Color.red(),
        "Nira":   discord.Color.gold(),
        "Boreal": discord.Color.blue(),
    }
    color = color_map.get(boss, discord.Color.purple())

    return obsidian_embed(
        "⚔️ Archon Hunt",
        "",
        color=color,
        fields=fields,
        footer="warframestat.us • Tap 🔄 to refresh",
        client=client,
    )


async def _refresh_archon(interaction: discord.Interaction):
    """Refresh callback for RefreshView; respects a per-user 30s cooldown."""
    now = time.monotonic()
    last = _last_refresh.get(interaction.user.id, 0.0)
    remaining = _REFRESH_COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        return await interaction.followup.send(
            f"⏳ Slow down — try again in {int(remaining) + 1}s.",
            ephemeral=True,
        )
    _last_refresh[interaction.user.id] = now

    archon_data = await fetch_archon_hunt_data()
    if not archon_data:
        return await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client), ephemeral=True
        )
    embed = build_archon_embed(archon_data, interaction.client)
    await interaction.edit_original_response(embed=embed, view=RefreshView(_refresh_archon))


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
                embed=warframe_data_unavailable_embed(interaction.client),
                ephemeral=True,
            )
        embed = build_archon_embed(archon_data, interaction.client)
        await interaction.followup.send(embed=embed, view=RefreshView(_refresh_archon), ephemeral=False)
