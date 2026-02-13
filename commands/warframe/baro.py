"""Baro Ki'Teer tracker command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed, format_number, EMBED_COLORS
from warframe_api import get_baro_status
from views import RetryView, RefreshView
from database import DB_PATH
import aiosqlite
import dateparser


def _parse_baro_item_name(item: dict) -> str:
    """Extract readable item name from API response. Handles 'item', 'itemType', 'itemName'."""
    name = item.get("item") or item.get("itemName")
    if name:
        return str(name)
    raw = item.get("itemType", "")
    if not raw:
        return "Unknown"
    # itemType is often a path like /Lotus/StoreItems/Mods/PrimeMod - use last segment, clean up
    parts = str(raw).strip("/").split("/")
    last = parts[-1] if parts else raw
    return last.replace("_", " ").replace("-", " ").title()


def format_baro_time(expiry_time: datetime) -> str:
    """Format time remaining for Baro."""
    time_remaining = expiry_time - datetime.now(timezone.utc)
    total_seconds = int(time_remaining.total_seconds())
    
    # Handle negative time (shouldn't happen if Baro is active, but be safe)
    if total_seconds < 0:
        return "Expired"
    
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    
    # Format with days if applicable
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def build_baro_embed(baro_data: dict, is_active: bool, client) -> discord.Embed:
    """Build the Baro embed. Used for both initial display and updates."""
    location = baro_data.get("location", "Unknown")
    activation = baro_data.get("activation", "")
    expiry = baro_data.get("expiry", "")
    inventory = baro_data.get("inventory", [])
    
    if is_active:
        # Baro is currently active
        try:
            expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
            if expiry_time:
                time_str = format_baro_time(expiry_time)
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
                item_name = _parse_baro_item_name(item)
                ducats = int(item.get("ducats") or item.get("ducatPrice") or 0)
                credits = int(item.get("credits") or item.get("creditPrice") or 0)
                total_ducats += ducats
                total_credits += credits
                inventory_list += f"`{item_name}`\n"
                inventory_list += f"💎 {format_number(ducats)} ducats • 💰 {format_number(credits)} credits\n\n"
            
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
            fields.append(("💰 Total Cost", f"💎 **{format_number(total_ducats)} ducats**\n💰 **{format_number(total_credits)} credits**", True))
        
        embed = obsidian_embed(
            "🛒 Baro Ki'Teer",
            "🟢 **Currently Active**",
            color=EMBED_COLORS["warframe"],
            thumbnail="https://vignette.wikia.nocookie.net/warframe/images/4/4a/BaroKiTeer.png/revision/latest?cb=20150213150000",
            fields=fields,
            footer=f"PC data • Use Refresh • See also: /warframe cycles, /warframe alerts",
            client=client,
        )
    else:
        # Baro is not active - show prominent countdown
        fields = []
        countdown_line = ""
        if activation:
            try:
                activation_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if activation_time:
                    time_until = activation_time - datetime.now(timezone.utc)
                    if time_until.total_seconds() > 0:
                        total_s = int(time_until.total_seconds())
                        days = total_s // 86400
                        hours = (total_s % 86400) // 3600
                        mins = (total_s % 3600) // 60
                        time_str = f"{days}d {hours}h {mins}m"
                        arrival_discord = f"<t:{int(activation_time.timestamp())}:R>"
                        countdown_line = f"\n\n**Countdown:** {time_str} until arrival\n{arrival_discord}"
                        fields = [
                            ("⏰ Next Arrival", f"{time_str}\n{arrival_discord}", True),
                            ("📍 Location", location if location != 'Unknown' else 'TBA', True),
                        ]
                    else:
                        time_str = "Recently departed"
                        arrival_discord = "Recently departed"
                        countdown_line = "\n\nBaro just left. Next visit in ~2 weeks."
                        fields = [("⏰ Status", "Recently departed", True), ("📍 Location", location if location != 'Unknown' else 'TBA', True)]
                else:
                    time_str = "Unknown"
                    arrival_discord = "Unknown"
                    fields = [("⏰ Next Arrival", "Unknown", True), ("📍 Location", location if location != 'Unknown' else 'TBA', True)]
            except Exception:
                time_str = "Unknown"
                arrival_discord = "Unknown"
                fields = [("⏰ Next Arrival", "Unknown", True), ("📍 Location", location if location != 'Unknown' else 'TBA', True)]

        embed = obsidian_embed(
            "🛒 Baro Ki'Teer",
            "🔴 **Not Currently Active**\n\nPrepare your ducats for the next visit!" + countdown_line,
            color=EMBED_COLORS["warframe"],
            thumbnail="https://vignette.wikia.nocookie.net/warframe/images/4/4a/BaroKiTeer.png/revision/latest?cb=20150213150000",
            fields=fields,
            footer=f"PC data • Last updated <t:{int(datetime.now(timezone.utc).timestamp())}:R> • Baro visits every ~2 weeks",
            client=client,
        )
    
    return embed


def setup(bot, group=None):
    """Register the baro command."""
    command_decorator = group.command(name="baro", description="View Baro Ki'Teer's current visit and inventory.") if group else bot.tree.command(name="baro", description="View Baro Ki'Teer's current visit and inventory.")
    
    @command_decorator
    async def baro(interaction: discord.Interaction):
        """Display Baro Ki'Teer's current status and inventory."""
        await interaction.response.defer(ephemeral=False)
        
        is_active, baro_data = await get_baro_status()
        
        if not baro_data:
            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message("Only the person who ran this can retry.", ephemeral=True)
                await btn_interaction.response.defer()
                is_active, new_data = await get_baro_status()
                if not new_data:
                    return await btn_interaction.followup.send("Still unable to fetch. Try again later.", ephemeral=True)
                emb = build_baro_embed(new_data, is_active, interaction.client)
                await btn_interaction.message.edit(embed=emb, view=None)
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Could not fetch Baro Ki'Teer data from Warframe API. Please try again later.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                view=RetryView(on_retry),
                ephemeral=True,
            )
        
        embed = build_baro_embed(baro_data, is_active, interaction.client)

        async def on_refresh(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.response.send_message("Only the person who ran this can refresh.", ephemeral=True)
            await btn_interaction.response.defer()
            from cache_utils import invalidate
            invalidate("warframe:baro")
            new_active, new_data = await get_baro_status()
            if not new_data:
                await btn_interaction.followup.send("Could not fetch fresh data. Try again later.", ephemeral=True)
                return
            new_emb = build_baro_embed(new_data, new_active, interaction.client)
            view = RefreshView(on_refresh)
            await btn_interaction.message.edit(embed=new_emb, view=view)

        view = RefreshView(on_refresh)
        message = await interaction.followup.send(embed=embed, view=view, ephemeral=False)

        # If Baro is active, store the message for live updates
        if is_active:
            expiry = baro_data.get("expiry", "")
            if expiry:
                try:
                    expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                    if expiry_time:
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute("""
                                INSERT OR REPLACE INTO baro_live_messages 
                                (guild_id, channel_id, message_id, expiry_time, created_at)
                                VALUES (?, ?, ?, ?, ?)
                            """, (
                                interaction.guild.id,
                                interaction.channel.id,
                                message.id,
                                expiry_time.isoformat(),
                                datetime.now(timezone.utc).isoformat()
                            ))
                            await db.commit()
                except Exception as e:
                    # Log error but don't fail the command
                    import logging
                    logging.getLogger(__name__).error(f"Error storing Baro message for live updates: {e}")
