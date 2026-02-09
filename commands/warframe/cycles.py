"""Open World Cycle Tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from warframe_api import get_all_cycles
import dateparser


def format_time_remaining(expiry_time: datetime) -> str:
    """Format time remaining until cycle change."""
    now = datetime.now(timezone.utc)
    time_remaining = expiry_time - now

    if time_remaining.total_seconds() <= 0:
        return "Just changed"

    total_seconds = int(time_remaining.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


def format_cycle_progress(expiry_time: datetime, cycle_total_seconds: int) -> tuple[str, str]:
    """Return (countdown_str, progress_bar) for a cycle. E.g. Cetus: 150 min (100 day + 50 night)."""
    now = datetime.now(timezone.utc)
    elapsed = (expiry_time - now).total_seconds()
    if elapsed <= 0:
        return "Just changed", "██████████ 0%"
    if cycle_total_seconds <= 0:
        return format_time_remaining(expiry_time), ""
    # Elapsed = time until change, so remaining = elapsed. Progress = (total - elapsed) / total
    remaining_pct = min(100, max(0, int(100 * elapsed / cycle_total_seconds)))
    filled = int(remaining_pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return format_time_remaining(expiry_time), f"{bar} {remaining_pct}%"


def setup(bot, group=None):
    """Register the cycles command."""
    command_decorator = group.command(name="cycles", description="Check current open world cycle status (Cetus, Fortuna, Deimos).") if group else bot.tree.command(name="cycles", description="Check current open world cycle status (Cetus, Fortuna, Deimos).")
    
    @command_decorator
    async def cycles(interaction: discord.Interaction):
        """Display current cycle status for all open worlds."""
        await interaction.response.defer(ephemeral=False)
        
        cycles_data = await get_all_cycles()
        
        if not cycles_data or not any(cycles_data.values()):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Could not fetch cycle data from Warframe API. Please try again later.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        fields = []
        
        # Cetus Cycle (Plains of Eidolon) - 100 min day, 50 min night
        CETUS_CYCLE_SECONDS = 150 * 60
        cetus = cycles_data.get('cetus')
        if cetus:
            is_day = cetus.get('isDay', False)
            state = "☀️ Day" if is_day else "🌙 Night"
            expiry = cetus.get('expiry', '')

            try:
                expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if expiry_time:
                    time_str, progress_bar = format_cycle_progress(expiry_time, CETUS_CYCLE_SECONDS)
                    value = f"{state}\n⏱️ {time_str}\n{progress_bar}\n🕐 Ends: <t:{int(expiry_time.timestamp())}:F>\n<t:{int(expiry_time.timestamp())}:R>"
                else:
                    value = state
            except Exception:
                value = state

            fields.append(("🌅 Cetus", value, True))
        
        # Fortuna Cycle (Orb Vallis) - 20 min warm, 20 min cold
        VALLIS_CYCLE_SECONDS = 40 * 60
        vallis = cycles_data.get('vallis')
        if vallis:
            is_warm = vallis.get('isWarm', False)
            state = "🔥 Warm" if is_warm else "❄️ Cold"
            expiry = vallis.get('expiry', '')

            try:
                expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if expiry_time:
                    time_str, progress_bar = format_cycle_progress(expiry_time, VALLIS_CYCLE_SECONDS)
                    value = f"{state}\n⏱️ {time_str}\n{progress_bar}\n🕐 Ends: <t:{int(expiry_time.timestamp())}:F>\n<t:{int(expiry_time.timestamp())}:R>"
                else:
                    value = state
            except Exception:
                value = state

            fields.append(("❄️ Fortuna", value, True))
        
        # Deimos Cycle (Cambion Drift) - ~4h Fass, ~4h Vome
        CAMBION_CYCLE_SECONDS = 8 * 3600
        cambion = cycles_data.get('cambion')
        if cambion:
            state = cambion.get('state', 'Unknown')
            state_display = "🔴 Fass" if state.lower() == 'fass' else "🟢 Vome" if state.lower() == 'vome' else state.title()
            expiry = cambion.get('expiry', '')

            try:
                expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if expiry_time:
                    time_str, progress_bar = format_cycle_progress(expiry_time, CAMBION_CYCLE_SECONDS)
                    value = f"{state_display}\n⏱️ {time_str}\n{progress_bar}\n🕐 Ends: <t:{int(expiry_time.timestamp())}:F>\n<t:{int(expiry_time.timestamp())}:R>"
                else:
                    value = state_display
            except Exception:
                value = state_display

            fields.append(("🦠 Deimos", value, True))
        
        if not fields:
            desc = "No cycle data available."
        else:
            desc = None
        
        embed = obsidian_embed(
            "🌍 Open World Cycles",
            desc or "",
            color=discord.Color.blue(),
            fields=fields if fields else None,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=False)
