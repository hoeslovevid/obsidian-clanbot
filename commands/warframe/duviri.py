"""Duviri Circuit command."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser  # type: ignore

from utils import obsidian_embed
from warframe_api import fetch_duviri_circuit


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
        
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        
        return " ".join(parts) if parts else "Less than 1 minute"
    except Exception:
        return "Unknown"


def setup(bot, group=None):
    """Register the duviri command."""
    
    command_decorator = group.command(name="duviri", description="View current Duviri Circuit rotations and progress.") if group else bot.tree.command(name="duviri", description="View current Duviri Circuit rotations and progress.")
    
    @command_decorator
    async def duviri(interaction: discord.Interaction):
        """Display current Duviri Circuit information."""
        await interaction.response.defer()
        
        data = await fetch_duviri_circuit()
        
        if not data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Failed to fetch Duviri Circuit data. Please try again later.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        # Extract circuit data
        state = data.get("state", "Unknown")
        expiry = data.get("expiry", "")
        time_remaining = format_time_remaining(expiry) if expiry else "Unknown"
        
        # Get current rotation
        current_rotation = data.get("choices", [])
        
        # Build description
        desc = f"**Status:** {state.title()}\n"
        desc += f"**Time Remaining:** {time_remaining}\n\n"
        
        if current_rotation:
            desc += "**Current Rotation:**\n"
            for i, choice in enumerate(current_rotation, 1):
                choice_type = choice.get("category", "Unknown")
                choice_name = choice.get("choices", [])
                
                if choice_type == "warframe":
                    desc += f"**Warframe {i}:** {', '.join(choice_name) if choice_name else 'None'}\n"
                elif choice_type == "weapon":
                    desc += f"**Weapon {i}:** {', '.join(choice_name) if choice_name else 'None'}\n"
                else:
                    desc += f"**{choice_type.title()} {i}:** {', '.join(choice_name) if choice_name else 'None'}\n"
        else:
            desc += "No rotation data available."
        
        embed = obsidian_embed(
            "🌊 Duviri Circuit",
            desc,
            color=discord.Color.blue(),
            thumbnail=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None,
            footer="warframestat.us • Refreshes every 60s • Timestamps in your timezone",
            client=interaction.client,
        )
        
        if expiry:
            try:
                expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if expiry_time:
                    embed.timestamp = expiry_time
            except Exception:
                pass
        
        await interaction.followup.send(embed=embed)
