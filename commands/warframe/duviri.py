"""Duviri Circuit command."""
import discord
from discord import app_commands
from datetime import datetime, timezone
import dateparser  # type: ignore

from core.utils import obsidian_embed, warframe_data_unavailable_embed
from api.warframe_api import fetch_duviri_circuit
from core.refresh_panels import register_refresh_panel
from core.wf_retry_panels import send_wf_retry_message
from views import RefreshView


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


def build_duviri_embed(
    data: dict,
    client,
    *,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    """Build Duviri Circuit embed from API payload."""
    state = data.get("state", "Unknown")
    expiry = data.get("expiry", "")
    time_remaining = format_time_remaining(expiry) if expiry else "Unknown"
    current_rotation = data.get("choices", [])

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
        category="warframe",
        thumbnail=guild.icon.url if guild and guild.icon else None,
        footer="warframestat.us · Refreshes every 60s",
        client=client,
    )

    if expiry:
        try:
            expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            if expiry_time:
                embed.timestamp = expiry_time
        except Exception:
            pass

    return embed


def setup(bot, group=None):
    """Register the duviri command."""
    
    command_decorator = group.command(name="duviri", description="View current Duviri Circuit rotations and progress.") if group else bot.tree.command(name="duviri", description="View current Duviri Circuit rotations and progress.")
    
    @command_decorator
    async def duviri(interaction: discord.Interaction):
        """Display current Duviri Circuit information."""
        await interaction.response.defer()
        
        data = await fetch_duviri_circuit()

        if not data:
            return await send_wf_retry_message(
                interaction,
                embed=warframe_data_unavailable_embed(interaction.client),
                retry_type="wf_duviri",
                payload={},
                owner_user_id=interaction.user.id,
                fetch_probe=fetch_duviri_circuit,
                edit=False,
            )
        
        embed = build_duviri_embed(data, interaction.client, guild=interaction.guild)
        view = RefreshView.panel("wf_duviri")
        msg = await interaction.followup.send(embed=embed, view=view)
        await register_refresh_panel(msg, "wf_duviri", {})
