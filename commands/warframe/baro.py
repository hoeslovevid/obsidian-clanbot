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
                    expiry_discord = f"<t:{int(expiry_time.timestamp())}:R>"
                else:
                    time_str = "Unknown"
                    expiry_discord = "Unknown"
            except Exception:
                time_str = "Unknown"
                expiry_discord = "Unknown"
            
            # Build inventory list
            inventory_list = ""
            total_ducats = 0
            total_credits = 0
            
            if inventory:
                for item in inventory[:15]:  # Limit to 15 items to avoid embed limits
                    item_name = item.get("item", "Unknown")
                    ducats = item.get("ducats", 0)
                    credits = item.get("credits", 0)
                    total_ducats += ducats
                    total_credits += credits
                    inventory_list += f"`{item_name}`\n"
                    inventory_list += f"💎 {ducats} ducats • 💰 {credits:,} credits\n\n"
                
                if len(inventory) > 15:
                    inventory_list += f"_...and {len(inventory) - 15} more items_"
            else:
                inventory_list = "Inventory not available yet."
            
            fields = [
                ("📍 Location", location, True),
                ("⏰ Time Remaining", f"{time_str}\n{expiry_discord}", True),
                ("📦 Inventory", inventory_list, False),
            ]
            
            if inventory:
                fields.append(("💰 Total Cost", f"💎 **{total_ducats} ducats**\n💰 **{total_credits:,} credits**", True))
            
            embed = obsidian_embed(
                "🛒 Baro Ki'Teer",
                "🟢 **Currently Active**",
                color=discord.Color.green(),
                thumbnail="https://vignette.wikia.nocookie.net/warframe/images/4/4a/BaroKiTeer.png/revision/latest?cb=20150213150000",
                fields=fields,
                client=interaction.client,
            )
        else:
            # Baro is not active
            fields = []
            if activation:
                try:
                    activation_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                    if activation_time:
                        time_until = activation_time - datetime.now(timezone.utc)
                        if time_until.total_seconds() > 0:
                            days = int(time_until.total_seconds() // 86400)
                            hours = int((time_until.total_seconds() % 86400) // 3600)
                            time_str = f"{days}d {hours}h"
                            arrival_discord = f"<t:{int(activation_time.timestamp())}:R>"
                        else:
                            time_str = "Recently departed"
                            arrival_discord = "Recently departed"
                    else:
                        time_str = "Unknown"
                        arrival_discord = "Unknown"
                except Exception:
                    time_str = "Unknown"
                    arrival_discord = "Unknown"
                
                fields = [
                    ("⏰ Next Arrival", f"{time_str}\n{arrival_discord}", True),
                    ("📍 Location", location if location != 'Unknown' else 'TBA', True),
                ]
            
            embed = obsidian_embed(
                "🛒 Baro Ki'Teer",
                "🔴 **Not Currently Active**\n\nPrepare your ducats for the next visit!",
                color=discord.Color.orange(),
                thumbnail="https://vignette.wikia.nocookie.net/warframe/images/4/4a/BaroKiTeer.png/revision/latest?cb=20150213150000",
                fields=fields,
                client=interaction.client,
            )
        
        await interaction.followup.send(embed=embed, ephemeral=False)
