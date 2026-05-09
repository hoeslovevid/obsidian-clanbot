"""Invasions tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from core.utils import obsidian_embed, warframe_data_unavailable_embed, BUTTON_ONLY_RUNNER_MSG, render_bar
from api.warframe_api import fetch_invasions
from views import RetryView, RefreshView
from core.cache_utils import invalidate
import dateparser


def _build_invasions_embed(invasions_data, client):
    """Build the invasions embed. Used for initial display and refresh."""
    invasions_data = sorted(invasions_data, key=lambda x: x.get("completion", 0))
    now_utc = datetime.now(timezone.utc)
    fields = []
    for inv in invasions_data[:5]:
        node = inv.get("node") or inv.get("nodeKey", "Unknown Location")
        att_obj = inv.get("attacker") or {}
        def_obj = inv.get("defender") or {}
        attacker = att_obj.get("faction") or att_obj.get("factionKey", "Unknown")
        defender = def_obj.get("faction") or def_obj.get("factionKey", "Unknown")
        completion = inv.get("completion", 0)
        count = inv.get("count", 0)
        required_runs = inv.get("requiredRuns", 0)

        att_reward = att_obj.get("reward") or {}
        def_reward = def_obj.get("reward") or {}
        att_counted = att_reward.get("countedItems", [])
        def_counted = def_reward.get("countedItems", [])

        attacker_reward_str = "None"
        if att_counted:
            items = [item.get("type") or item.get("key", "?") for item in att_counted]
            attacker_reward_str = ", ".join(items[:2]) + (f" +{len(items) - 2}" if len(items) > 2 else "")

        defender_reward_str = "None"
        if def_counted:
            items = [item.get("type") or item.get("key", "?") for item in def_counted]
            defender_reward_str = ", ".join(items[:2]) + (f" +{len(items) - 2}" if len(items) > 2 else "")

        pct = max(0, min(100, float(completion)))

        time_str = "—"
        activation = inv.get("activation")
        if activation:
            try:
                act_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if act_time:
                    act_utc = act_time.replace(tzinfo=timezone.utc) if act_time.tzinfo is None else act_time
                    elapsed = now_utc - act_utc
                    total_sec = max(0, int(elapsed.total_seconds()))
                    hours = total_sec // 3600
                    minutes = (total_sec % 3600) // 60
                    time_str = f"{hours}h {minutes}m active"
            except Exception:
                pass

        value = f"**{attacker}** ⚔️ **{defender}**\n"
        value += f"{render_bar(pct, length=10)}\n"
        value += f"⏱️ {time_str}\n"
        if required_runs:
            value += f"Runs: {count:,}/{required_runs:,}\n"
        value += f"\n**{attacker}:** {attacker_reward_str}\n"
        value += f"**{defender}:** {defender_reward_str}"

        fields.append((f"📍 {node}", value, False))

    desc = f"**{len(invasions_data)} Active Invasion{'s' if len(invasions_data) != 1 else ''}**"
    if len(invasions_data) > 5:
        desc += f"\n_Showing 5 of {len(invasions_data)} invasions_"

    return obsidian_embed(
        "⚔️ Active Invasions",
        desc,
        color=discord.Color.orange(),
        fields=fields,
        footer="warframestat.us • Refreshes every 60s",
        client=client,
    )


def setup(bot, group=None):
    """Register the invasions command."""
    command_decorator = group.command(name="invasions", description="View active faction invasions with rewards.") if group else bot.tree.command(name="invasions", description="View active faction invasions with rewards.")

    @command_decorator
    async def invasions(interaction: discord.Interaction):
        """Display all active invasions."""
        await interaction.response.defer(ephemeral=False)

        invasions_data = await fetch_invasions()

        if invasions_data is None:
            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                new_data = await fetch_invasions()
                if new_data is None:
                    return await btn_interaction.followup.send(
                        "Invasions still won't load. Try **Try again** again in a minute.",
                        ephemeral=True,
                    )
                emb = _build_invasions_embed(new_data, interaction.client)
                await btn_interaction.message.edit(embed=emb, view=None)

            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=RetryView(on_retry),
            )

        if not invasions_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Active Invasions",
                    "No active invasions at this time. Check back later!",
                    color=discord.Color.blue(),
                    footer="warframestat.us",
                    client=interaction.client,
                ),
            )

        async def on_refresh(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            await btn_interaction.response.defer()
            invalidate("warframe:invasions")
            new_data = await fetch_invasions()
            if new_data is None:
                return await btn_interaction.followup.send(
                    "Couldn't refresh invasions yet — stats API is still busy.",
                    ephemeral=True,
                )
            emb = _build_invasions_embed(new_data, interaction.client)
            await btn_interaction.message.edit(embed=emb, view=RefreshView(on_refresh, timeout=300))

        embed = _build_invasions_embed(invasions_data, interaction.client)
        await interaction.followup.send(embed=embed, view=RefreshView(on_refresh, timeout=300))
