"""Open World Cycle Tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from warframe_api import get_all_cycles
from views import RetryView, RefreshView
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
    # elapsed = time remaining until cycle ends. Progress = (total - remaining) / total
    time_elapsed = cycle_total_seconds - elapsed
    progress_pct = min(100, max(0, int(100 * time_elapsed / cycle_total_seconds)))
    filled = int(progress_pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return format_time_remaining(expiry_time), f"{bar} {progress_pct}%"


def _build_cycle_fields(cycles_data: dict) -> list:
    """Build embed fields from cycle data. Handles graceful degradation (partial data)."""
    fields = []
    CETUS_CYCLE_SECONDS = 150 * 60
    VALLIS_CYCLE_SECONDS = 40 * 60
    CAMBION_CYCLE_SECONDS = 8 * 3600

    if cycles_data.get('cetus'):
        cetus = cycles_data['cetus']
        is_day = cetus.get('isDay', False)
        state = "☀️ Day" if is_day else "🌙 Night"
        expiry = cetus.get('expiry', '')
        try:
            expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            if expiry_time:
                time_str, progress_bar = format_cycle_progress(expiry_time, CETUS_CYCLE_SECONDS)
                value = f"{state}\n⏱️ {time_str}\n{progress_bar}\n🕐 <t:{int(expiry_time.timestamp())}:F>\n<t:{int(expiry_time.timestamp())}:R>"
            else:
                value = state
        except Exception:
            value = state
        fields.append(("🌅 Cetus", value, True))

    if cycles_data.get('vallis'):
        vallis = cycles_data['vallis']
        is_warm = vallis.get('isWarm', False)
        state = "🔥 Warm" if is_warm else "❄️ Cold"
        expiry = vallis.get('expiry', '')
        try:
            expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            if expiry_time:
                time_str, progress_bar = format_cycle_progress(expiry_time, VALLIS_CYCLE_SECONDS)
                value = f"{state}\n⏱️ {time_str}\n{progress_bar}\n🕐 <t:{int(expiry_time.timestamp())}:F>\n<t:{int(expiry_time.timestamp())}:R>"
            else:
                value = state
        except Exception:
            value = state
        fields.append(("❄️ Fortuna", value, True))

    if cycles_data.get('cambion'):
        cambion = cycles_data['cambion']
        state = cambion.get('state', 'Unknown')
        state_display = "🔴 Fass" if state.lower() == 'fass' else "🟢 Vome" if state.lower() == 'vome' else state.title()
        expiry = cambion.get('expiry', '')
        try:
            expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            if expiry_time:
                time_str, progress_bar = format_cycle_progress(expiry_time, CAMBION_CYCLE_SECONDS)
                value = f"{state_display}\n⏱️ {time_str}\n{progress_bar}\n🕐 <t:{int(expiry_time.timestamp())}:F>\n<t:{int(expiry_time.timestamp())}:R>"
            else:
                value = state_display
        except Exception:
            value = state_display
        fields.append(("🦠 Deimos", value, True))

    return fields


def setup(bot, group=None):
    """Register the cycles command."""
    command_decorator = group.command(name="cycles", description="Check current open world cycle status (Cetus, Fortuna, Deimos).") if group else bot.tree.command(name="cycles", description="Check current open world cycle status (Cetus, Fortuna, Deimos).")

    @command_decorator
    async def cycles(interaction: discord.Interaction):
        """Display current cycle status for all open worlds."""
        await interaction.response.defer(ephemeral=False)

        cycles_data = await get_all_cycles()
        success = {k: v for k, v in (cycles_data or {}).items() if v is not None}
        failed = [k for k in ('cetus', 'vallis', 'cambion') if k not in success]

        if not success:
            embed = obsidian_embed(
                "❌ Error",
                "Could not fetch cycle data from Warframe API. The service may be temporarily unavailable.",
                color=discord.Color.red(),
                client=interaction.client,
            )

            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message("Only the person who ran this can retry.", ephemeral=True)
                await btn_interaction.response.defer()
                from cache_utils import invalidate
                invalidate("warframe:cycles")
                new_data = await get_all_cycles()
                new_success = {k: v for k, v in (new_data or {}).items() if v is not None}
                if not new_success:
                    await btn_interaction.followup.send("Still unable to fetch. Try again later.", ephemeral=True)
                    return
                fields = _build_cycle_fields(new_success)
                desc = "Partial data (some cycles unavailable)." if len(new_success) < 3 else ""
                emb = obsidian_embed("🌍 Open World Cycles", desc, color=discord.Color.blue(), fields=fields, client=interaction.client)
                await btn_interaction.message.edit(embed=emb, view=None)

            view = RetryView(on_retry)
            return await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        fields = _build_cycle_fields(success)
        desc = "Partial data: " + ", ".join(failed) + " unavailable." if failed else ""

        if not fields:
            desc = "No cycle data available."
        else:
            desc = None

        embed = obsidian_embed(
            "🌍 Open World Cycles",
            desc or "",
            color=discord.Color.blue(),
            fields=fields if fields else None,
            thumbnail=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None,
            footer="Cetus • Fortuna • Deimos • Use Refresh to update",
            client=interaction.client,
        )

        async def on_refresh(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.response.send_message("Only the person who ran this can refresh.", ephemeral=True)
            await btn_interaction.response.defer()
            from cache_utils import invalidate
            invalidate("warframe:cycles")
            new_data = await get_all_cycles()
            new_success = {k: v for k, v in (new_data or {}).items() if v is not None}
            if not new_success:
                await btn_interaction.followup.send("Could not fetch fresh data. Try again later.", ephemeral=True)
                return
            new_fields = _build_cycle_fields(new_success)
            new_failed = [k for k in ("cetus", "vallis", "cambion") if k not in new_success]
            new_desc = "Partial data: " + ", ".join(new_failed) + " unavailable." if new_failed else ""
            new_emb = obsidian_embed("🌍 Open World Cycles", new_desc or "", color=discord.Color.blue(), fields=new_fields, client=interaction.client)
            view = RefreshView(on_refresh)
            await btn_interaction.message.edit(embed=new_emb, view=view)

        view = RefreshView(on_refresh)
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)
