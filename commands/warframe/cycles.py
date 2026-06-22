"""Open World Cycle Tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from core.cycles_live import build_cycle_fields as _build_cycle_fields
from core.utils import obsidian_embed, EMBED_COLORS, warframe_data_unavailable_embed, BUTTON_ONLY_RUNNER_MSG
from core.wf_resolve import (
    wf_cycles_split,
    wf_footer_with_freshness,
    wf_invalidate,
)
from api.warframe_api import get_all_cycles
from core.refresh_panels import register_refresh_panel
from core.wf_retry_panels import send_wf_retry_message
from views import RefreshView


def setup(bot, group=None):
    """Register the cycles command."""
    command_decorator = group.command(name="cycles", description="Check current open world cycle status (Cetus, Fortuna, Deimos).") if group else bot.tree.command(name="cycles", description="Check current open world cycle status (Cetus, Fortuna, Deimos).")

    @command_decorator
    async def cycles(interaction: discord.Interaction):
        """Display current cycle status for all open worlds."""
        await interaction.response.defer(ephemeral=False)

        cycles_data = await get_all_cycles()
        success, failed = wf_cycles_split(cycles_data)

        if not success:
            return await send_wf_retry_message(
                interaction,
                embed=warframe_data_unavailable_embed(interaction.client),
                retry_type="wf_cycles",
                payload={},
                owner_user_id=interaction.user.id,
                fetch_probe=get_all_cycles,
                edit=False,
                ephemeral=True,
            )

        fields = _build_cycle_fields(success)
        desc = "Partial data: " + ", ".join(failed) + " unavailable." if failed else ""

        if not fields:
            desc = "No cycle data available."
        else:
            desc = desc or None

        embed = obsidian_embed(
            "🌍 Open World Cycles",
            desc or "",
            color=EMBED_COLORS["warframe"],
            fields=fields if fields else None,
            thumbnail=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None,
            footer=wf_footer_with_freshness(
                "See also: /warframe baro, /warframe alerts • **Update data** refreshes",
                "warframe:cycles",
            ),
            client=interaction.client,
        )

        view = RefreshView.panel("wf_cycles")
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=False)
        await register_refresh_panel(msg, "wf_cycles", {})
