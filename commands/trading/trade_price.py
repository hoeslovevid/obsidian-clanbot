"""Price checking command using Warframe Market API."""
import discord
from discord import app_commands

from utils import obsidian_embed
from warframe_api import search_warframe_market_item, get_warframe_market_price


def setup(bot):
    """Register the trade_price command."""
    @bot.tree.command(name="trade_price", description="Check current market prices for a Warframe item.")
    @app_commands.describe(
        item="Item name (e.g., 'Mesa Prime Set', 'Primed Continuity')",
        platform="Platform (default: PC)"
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="PC", value="pc"),
        app_commands.Choice(name="Xbox", value="xbox"),
        app_commands.Choice(name="PlayStation", value="ps4"),
        app_commands.Choice(name="Switch", value="switch"),
    ])
    async def trade_price(
        interaction: discord.Interaction,
        item: str,
        platform: app_commands.Choice[str] = None
    ):
        """Check market prices for an item."""
        await interaction.response.defer(ephemeral=True)
        
        platform_val = platform.value if platform else "pc"
        
        # Search for item
        item_data = await search_warframe_market_item(item, platform_val)
        
        if not item_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Item Not Found",
                    f"Could not find '{item}' on Warframe Market. Please check the spelling and try again.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        item_name = item_data.get("item_name", item)
        item_url_name = item_data.get("url_name", "")
        
        # Get price data
        price_data = await get_warframe_market_price(item_url_name, platform_val)
        
        if not price_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Price Data Unavailable",
                    f"Could not fetch price data for '{item_name}'. The item may not be tradeable or have no active listings.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed
        fields = []
        
        # Sell orders (cheapest)
        sell_orders = price_data.get("sell_orders", [])[:5]
        if sell_orders:
            sell_list = []
            for order in sell_orders:
                price = order.get("platinum", 0)
                quantity = order.get("quantity", 1)
                mod_rank = order.get("mod_rank", 0)
                if mod_rank > 0:
                    sell_list.append(f"**{price}p** (R{mod_rank}, x{quantity})")
                else:
                    sell_list.append(f"**{price}p** (x{quantity})")
            fields.append(("💰 Cheapest Sellers", "\n".join(sell_list[:5]), False))
        
        # Buy orders (highest offers)
        buy_orders = price_data.get("buy_orders", [])[:5]
        if buy_orders:
            buy_list = []
            for order in buy_orders:
                price = order.get("platinum", 0)
                quantity = order.get("quantity", 1)
                mod_rank = order.get("mod_rank", 0)
                if mod_rank > 0:
                    buy_list.append(f"**{price}p** (R{mod_rank}, x{quantity})")
                else:
                    buy_list.append(f"**{price}p** (x{quantity})")
            fields.append(("💵 Highest Buyers", "\n".join(buy_list[:5]), False))
        
        # Price summary
        summary = []
        if price_data.get("lowest_sell"):
            summary.append(f"**Lowest Sell:** {price_data['lowest_sell']}p")
        if price_data.get("highest_buy"):
            summary.append(f"**Highest Buy:** {price_data['highest_buy']}p")
        
        # Get 90-day average if available
        stats = price_data.get("stats")
        if stats:
            avg_price = stats.get("avg_price")
            if avg_price:
                summary.append(f"**90-Day Average:** {avg_price:.0f}p")
        
        if summary:
            fields.append(("📊 Price Summary", "\n".join(summary), False))
        
        fields.append(("Platform", platform_val.upper(), True))
        
        # Add market link
        market_url = f"https://warframe.market/items/{item_url_name}"
        
        embed = obsidian_embed(
            f"💎 Market Prices: {item_name}",
            f"[View on Warframe Market]({market_url})",
            color=discord.Color.gold(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
