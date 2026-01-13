"""Invasions tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from warframe_api import fetch_invasions
import dateparser


def setup(bot):
    """Register the invasions command."""
    @bot.tree.command(name="invasions", description="View active faction invasions with rewards.")
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
        
        desc = f"**Active Invasions:** {len(invasions_data)}\n\n"
        
        for inv in invasions_data[:10]:  # Limit to first 10 invasions
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
                    attacker_reward_str = ", ".join(items[:3])  # Limit to first 3 items
                    if len(items) > 3:
                        attacker_reward_str += f" (+{len(items) - 3} more)"
            
            defender_reward_str = "None"
            if defender_reward:
                count = defender_reward.get("countedItems", [])
                if count:
                    items = [item.get("itemType", "Unknown") for item in count]
                    defender_reward_str = ", ".join(items[:3])  # Limit to first 3 items
                    if len(items) > 3:
                        defender_reward_str += f" (+{len(items) - 3} more)"
            
            # Calculate progress bar
            progress = int(completion / 100 * 10)  # 10 character progress bar
            progress_bar = "█" * progress + "░" * (10 - progress)
            
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
            
            desc += f"**{node}**\n"
            desc += f"`{attacker}` vs `{defender}`\n"
            desc += f"Progress: `{progress_bar}` {completion:.1f}%\n"
            desc += f"⏱️ ETA: {eta_str}\n"
            desc += f"**{attacker} Reward:** {attacker_reward_str}\n"
            desc += f"**{defender} Reward:** {defender_reward_str}\n\n"
        
        if len(invasions_data) > 10:
            desc += f"_...and {len(invasions_data) - 10} more invasions_"
        
        embed = obsidian_embed(
            "⚔️ Active Invasions",
            desc,
            color=discord.Color.orange(),
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed)
