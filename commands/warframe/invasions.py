"""Invasions tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from warframe_api import fetch_invasions
import dateparser


def setup(bot, group=None):
    """Register the invasions command."""
    command_decorator = group.command(name="invasions", description="View active faction invasions with rewards.") if group else bot.tree.command(name="invasions", description="View active faction invasions with rewards.")
    
    @command_decorator
    async def invasions(interaction: discord.Interaction):
        """Display all active invasions."""
        await interaction.response.defer(ephemeral=False)
        
        invasions_data = await fetch_invasions()
        
        if invasions_data is None:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Could not fetch invasion data from Warframe API. Please try again later.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        if not invasions_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Active Invasions",
                    "No active invasions at this time. Check back later!",
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
            )
        
        # Sort invasions by completion percentage (ascending - most urgent first)
        invasions_data.sort(key=lambda x: x.get("completion", 0))
        
        # Build fields for invasions (limit to 5 to avoid embed limits)
        # API uses attacker.faction, defender.faction and attacker.reward.countedItems[].type
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
            
            # Rewards from nested attacker.reward / defender.reward
            att_reward = att_obj.get("reward") or {}
            def_reward = def_obj.get("reward") or {}
            att_counted = att_reward.get("countedItems", [])
            def_counted = def_reward.get("countedItems", [])
            
            attacker_reward_str = "None"
            if att_counted:
                items = [item.get("type") or item.get("key", "?") for item in att_counted]
                attacker_reward_str = ", ".join(items[:2])
                if len(items) > 2:
                    attacker_reward_str += f" +{len(items) - 2}"
            
            defender_reward_str = "None"
            if def_counted:
                items = [item.get("type") or item.get("key", "?") for item in def_counted]
                defender_reward_str = ", ".join(items[:2])
                if len(items) > 2:
                    defender_reward_str += f" +{len(items) - 2}"
            
            # Progress bar (completion can be 0–100 or negative if defender ahead)
            pct = max(0, min(100, float(completion)))
            progress = int(pct / 100 * 8)
            progress_bar = "█" * progress + "░" * (8 - progress)
            
            # Time: show "Time active" from activation (API has no eta/expiry)
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
            
            # Build invasion field value
            value = f"**{attacker}** ⚔️ **{defender}**\n"
            value += f"`{progress_bar}` **{completion:.1f}%**\n"
            value += f"⏱️ {time_str}\n"
            if required_runs:
                value += f"Runs: {count:,}/{required_runs:,}\n"
            value += f"\n**{attacker}:** {attacker_reward_str}\n"
            value += f"**{defender}:** {defender_reward_str}"
            
            fields.append((f"📍 {node}", value, False))
        
        desc = f"**{len(invasions_data)} Active Invasion{'s' if len(invasions_data) != 1 else ''}**"
        if len(invasions_data) > 5:
            desc += f"\n_Showing 5 of {len(invasions_data)} invasions_"
        
        embed = obsidian_embed(
            "⚔️ Active Invasions",
            desc,
            color=discord.Color.orange(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed)
