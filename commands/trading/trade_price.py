"""Price checking command using Warframe Market API."""
import discord
from discord import app_commands

from utils import obsidian_embed, error_embed
from warframe_api import search_warframe_market_item, get_warframe_market_price

POPULAR_ITEMS = [
    "Mesa Prime Set", "Saryn Prime Set", "Rhino Prime Set", "Nova Prime Set",
    "Primed Continuity", "Primed Flow", "Primed Pressure Point", "Primed Reach",
    "Corrupted Mod", "Blind Rage", "Fleeting Expertise", "Overextended", "Narrow Minded",
    "Ash Prime Set", "Trinity Prime Set", "Valkyr Prime Set", "Nekros Prime Set",
    "Frost Prime Set", "Loki Prime Set", "Ember Prime Set", "Mag Prime Set",
]


async def item_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for item names. Paginated: top 25 by relevance."""
    from utils import AUTOCOMPLETE_MAX_CHOICES
    current_lower = (current or "").lower().strip()
    if not current_lower:
        matches = POPULAR_ITEMS[:AUTOCOMPLETE_MAX_CHOICES]
    else:
        exact = [i for i in POPULAR_ITEMS if i.lower() == current_lower]
        start = [i for i in POPULAR_ITEMS if i.lower().startswith(current_lower) and i not in exact]
        contains = [i for i in POPULAR_ITEMS if current_lower in i.lower() and i not in exact and i not in start]
        matches = (exact + start + contains)[:AUTOCOMPLETE_MAX_CHOICES]
    return [app_commands.Choice(name=m, value=m) for m in matches]


def setup(bot, group=None):
    """Register the trade_price command."""
    command_decorator = group.command(name="trade_price", description="Check current market prices for a Warframe item.") if group else bot.tree.command(name="trade_price", description="Check current market prices for a Warframe item.")
    
    @command_decorator
    @app_commands.describe(
        item="Item name (e.g., 'Mesa Prime Set', 'Primed Continuity')",
        platform="Platform (default: PC)"
    )
    @app_commands.autocomplete(item=item_autocomplete)
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
            hint = (
                "\n\nIf the bot runs on a server, the Warframe Market API may block requests. "
                "Set the **WARFRAME_MARKET_PROXY** (or **HTTPS_PROXY**) environment variable to an HTTP(S) proxy URL to try to bypass this."
            )
            return await interaction.followup.send(
                embed=error_embed(
                    "Item Not Found",
                    f"Could not find '{item}' on Warframe Market. Please check the spelling and try again.{hint}",
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
                embed=error_embed(
                    "Price Data Unavailable",
                    f"Could not fetch price data for '{item_name}'. The item may not be tradeable or have no active listings.",
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
