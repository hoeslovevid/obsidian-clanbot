"""Baro Ki'Teer tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from bot import get_baro_status, fetch_baro_data, DB_PATH
import aiosqlite
import dateparser


def setup(bot):
    """Register the baro command."""
    @bot.tree.command(name="baro", description="Check Baro Ki'Teer status and inventory.")
    async def baro(interaction: discord.Interaction):
        """Display Baro Ki'Teer's current status and inventory."""
        await interaction.response.defer(ephemeral=False)
        
        is_active, baro_data = await get_baro_status()
        
        if not baro_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Could not fetch Baro Ki'Teer data from Warframe API. Please try again later.",
                    color=discord.Color.red(),
                ),
                ephemeral=True
            )
        
        location = baro_data.get("location", "Unknown")
        activation = baro_data.get("activation", "")
        expiry = baro_data.get("expiry", "")
        inventory = baro_data.get("inventory", [])
        
        if is_active:
            # Baro is currently active
            try:
                expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if expiry_time:
                    time_remaining = expiry_time - datetime.now(timezone.utc)
                    hours = int(time_remaining.total_seconds() // 3600)
                    minutes = int((time_remaining.total_seconds() % 3600) // 60)
                    time_str = f"{hours}h {minutes}m"
                else:
                    time_str = "Unknown"
            except Exception:
                time_str = "Unknown"
            
            desc = f"**Status:** 🟢 Active\n"
            desc += f"**Location:** {location}\n"
            desc += f"**Time Remaining:** {time_str}\n\n"
            
            if inventory:
                desc += "**Inventory:**\n"
                total_ducats = 0
                total_credits = 0
                
                for item in inventory:
                    item_name = item.get("item", "Unknown")
                    ducats = item.get("ducats", 0)
                    credits = item.get("credits", 0)
                    total_ducats += ducats
                    total_credits += credits
                    desc += f"• **{item_name}** - {ducats} ducats, {credits:,} credits\n"
                
                desc += f"\n**Total Cost:** {total_ducats} ducats, {total_credits:,} credits"
            else:
                desc += "Inventory not available yet."
            
            embed = obsidian_embed(
                "🛒 Baro Ki'Teer - Active",
                desc,
                color=discord.Color.green(),
                thumbnail="https://vignette.wikia.nocookie.net/warframe/images/4/4a/BaroKiTeer.png/revision/latest?cb=20150213150000",
                client=interaction.client,
            )
        else:
            # Baro is not active
            if activation:
                try:
                    activation_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                    if activation_time:
                        time_until = activation_time - datetime.now(timezone.utc)
                        if time_until.total_seconds() > 0:
                            days = int(time_until.total_seconds() // 86400)
                            hours = int((time_until.total_seconds() % 86400) // 3600)
                            time_str = f"{days}d {hours}h"
                        else:
                            time_str = "Recently departed"
                    else:
                        time_str = "Unknown"
                except Exception:
                    time_str = "Unknown"
                
                desc = f"**Status:** 🔴 Not Active\n"
                desc += f"**Next Arrival:** {time_str}\n"
                desc += f"**Location:** {location if location != 'Unknown' else 'TBA'}\n\n"
                desc += "Baro Ki'Teer is not currently visiting. Prepare your ducats!"
            else:
                desc = "**Status:** 🔴 Not Active\n\n"
                desc += "Baro Ki'Teer is not currently visiting."
            
            embed = obsidian_embed(
                "🛒 Baro Ki'Teer - Inactive",
                desc,
                color=discord.Color.orange(),
                thumbnail="https://vignette.wikia.nocookie.net/warframe/images/4/4a/BaroKiTeer.png/revision/latest?cb=20150213150000",
                client=interaction.client,
            )
        
        await interaction.followup.send(embed=embed, ephemeral=False)
