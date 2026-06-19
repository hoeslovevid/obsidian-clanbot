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
    wf_retry_denied,
    wf_retry_guard,
)
from api.warframe_api import get_all_cycles
from views import RetryView, RefreshView


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
            embed = warframe_data_unavailable_embed(interaction.client)

            async def on_retry(btn_interaction: discord.Interaction):
                if not wf_retry_guard(btn_interaction, interaction.user.id):
                    return await wf_retry_denied(btn_interaction)
                await btn_interaction.response.defer()
                await wf_invalidate("warframe:cycles")
                new_data = await get_all_cycles()
                new_success, _ = wf_cycles_split(new_data)
                if not new_success:
                    await btn_interaction.followup.send(
                        "Still no cycle data. The stats service may need another minute.",
                        ephemeral=True,
                    )
                    return
                fields = _build_cycle_fields(new_success)
                desc = "Partial data (some cycles unavailable)." if len(new_success) < 3 else ""
                emb = obsidian_embed("🌍 Open World Cycles", desc, color=EMBED_COLORS["warframe"], fields=fields, client=interaction.client)
                await btn_interaction.message.edit(embed=emb, view=None)

            view = RetryView(on_retry)
            from core.wf_recovery import attach_notify_when_back
            attach_notify_when_back(view, get_all_cycles)
            return await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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

        async def on_refresh(btn_interaction: discord.Interaction):
            await wf_invalidate("warframe:cycles")
            new_data = await get_all_cycles()
            new_success, new_failed = wf_cycles_split(new_data)
            if not new_success:
                await btn_interaction.followup.send(
                    "Couldn't refresh cycles yet — try again in a moment.",
                    ephemeral=True,
                )
                return
            new_fields = _build_cycle_fields(new_success)
            partial = [k for k in ("cetus", "vallis", "cambion") if k not in new_success]
            new_desc = "Partial data: " + ", ".join(partial) + " unavailable." if partial else ""
            new_emb = obsidian_embed(
                "🌍 Open World Cycles",
                new_desc or "",
                color=EMBED_COLORS["warframe"],
                fields=new_fields,
                footer=wf_footer_with_freshness(
                    "See also: /warframe baro, /warframe alerts • **Update data** refreshes",
                    "warframe:cycles",
                ),
                client=interaction.client,
            )
            view = RefreshView(on_refresh)
            await btn_interaction.message.edit(embed=new_emb, view=view)

        view = RefreshView(on_refresh)
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)
