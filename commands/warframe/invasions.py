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
        fields = []
        for inv in invasions_data[:5]:
            node = inv.get("node", "Unknown Location")
            attacker = inv.get("attackingFaction", "Unknown")
            defender = inv.get("defendingFaction", "Unknown")
            completion = inv.get("completion", 0)
            eta = inv.get("eta", "")
            
            # Get rewards
            attacker_reward = inv.get("attackerReward", {})
            defender_reward = inv.get("defenderReward", {})
            
            attacker_reward_str = "None"
            if attacker_reward:
                count = attacker_reward.get("countedItems", [])
                if count:
                    items = [item.get("itemType", "Unknown") for item in count]
                    attacker_reward_str = ", ".join(items[:2])  # Limit to first 2 items
                    if len(items) > 2:
                        attacker_reward_str += f" +{len(items) - 2}"
            
            defender_reward_str = "None"
            if defender_reward:
                count = defender_reward.get("countedItems", [])
                if count:
                    items = [item.get("itemType", "Unknown") for item in count]
                    defender_reward_str = ", ".join(items[:2])  # Limit to first 2 items
                    if len(items) > 2:
                        defender_reward_str += f" +{len(items) - 2}"
            
            # Calculate progress bar
            progress = int(completion / 100 * 8)  # 8 character progress bar
            progress_bar = "█" * progress + "░" * (8 - progress)
            
            # Format ETA
            eta_str = "Unknown"
            if eta:
                try:
                    eta_time = dateparser.parse(eta, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                    if eta_time:
                        time_remaining = eta_time - datetime.now(timezone.utc)
                        hours = int(time_remaining.total_seconds() // 3600)
                        minutes = int((time_remaining.total_seconds() % 3600) // 60)
                        eta_str = f"{hours}h {minutes}m"
                except Exception:
                    pass
            
            # Build invasion field value
            value = f"`{attacker}` ⚔️ `{defender}`\n"
            value += f"`{progress_bar}` **{completion:.1f}%**\n"
            value += f"⏱️ {eta_str}\n\n"
            value += f"**{attacker}:** {attacker_reward_str}\n"
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
