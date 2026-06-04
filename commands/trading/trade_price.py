"""Price checking command using Warframe Market API."""
import discord
from discord import app_commands

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import obsidian_embed, error_embed, EMBED_COLORS, BUTTON_ONLY_RUNNER_MSG
from api.warframe_api import search_warframe_market_item, get_warframe_market_price
from views import RetryView, RefreshView
from core.cache_utils import invalidate

POPULAR_ITEMS = [
    "Mesa Prime Set", "Saryn Prime Set", "Rhino Prime Set", "Nova Prime Set",
    "Primed Continuity", "Primed Flow", "Primed Pressure Point", "Primed Reach",
    "Corrupted Mod", "Blind Rage", "Fleeting Expertise", "Overextended", "Narrow Minded",
    "Ash Prime Set", "Trinity Prime Set", "Valkyr Prime Set", "Nekros Prime Set",
    "Frost Prime Set", "Loki Prime Set", "Ember Prime Set", "Mag Prime Set",
]


async def item_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for item names. Paginated: top 25 by relevance."""
    from core.utils import AUTOCOMPLETE_MAX_CHOICES
    current_lower = (current or "").lower().strip()
    if not current_lower:
        matches = POPULAR_ITEMS[:AUTOCOMPLETE_MAX_CHOICES]
    else:
        exact = [i for i in POPULAR_ITEMS if i.lower() == current_lower]
        start = [i for i in POPULAR_ITEMS if i.lower().startswith(current_lower) and i not in exact]
        contains = [i for i in POPULAR_ITEMS if current_lower in i.lower() and i not in exact and i not in start]
        matches = (exact + start + contains)[:AUTOCOMPLETE_MAX_CHOICES]
    return [app_commands.Choice(name=m, value=m) for m in matches]


def _build_trade_embed(item_data: dict, price_data: dict, platform_val: str, client, author=None, fetched_at=None) -> discord.Embed:
    """Build the trade price embed from item and price data."""
    item_name = item_data.get("item_name", "Unknown")
    item_url_name = item_data.get("url_name", "")
    fields = []
    sell_orders = price_data.get("sell_orders", [])[:5]
    if sell_orders:
        sell_list = [f"**{o.get('platinum', 0)}p** (R{o.get('mod_rank', 0)}, x{o.get('quantity', 1)})" if o.get("mod_rank", 0) > 0 else f"**{o.get('platinum', 0)}p** (x{o.get('quantity', 1)})" for o in sell_orders]
        fields.append(("💰 Cheapest Sellers", "\n".join(sell_list[:5]), True))
    buy_orders = price_data.get("buy_orders", [])[:5]
    if buy_orders:
        buy_list = [f"**{o.get('platinum', 0)}p** (R{o.get('mod_rank', 0)}, x{o.get('quantity', 1)})" if o.get("mod_rank", 0) > 0 else f"**{o.get('platinum', 0)}p** (x{o.get('quantity', 1)})" for o in buy_orders]
        fields.append(("💵 Highest Buyers", "\n".join(buy_list[:5]), True))
    summary = []
    if price_data.get("lowest_sell"):
        summary.append(f"**Lowest Sell:** {price_data['lowest_sell']}p")
    if price_data.get("highest_buy"):
        summary.append(f"**Highest Buy:** {price_data['highest_buy']}p")
    stats = price_data.get("stats")
    if stats and stats.get("avg_price"):
        summary.append(f"**90-Day Avg:** {stats['avg_price']:.0f}p")
    if summary:
        fields.append(("📊 Summary", "\n".join(summary), True))
    fields.append(("Platform", platform_val.upper(), True))
    market_url = f"https://warframe.market/items/{item_url_name}"
    thumb = f"https://warframe.market/static/assets/icons/en/{item_url_name}.png" if item_url_name else None
    from datetime import datetime, timezone
    now = fetched_at or datetime.now(timezone.utc)
    ts = int(now.timestamp())
    footer = f"{footer_for('trading_price')} · {platform_val.upper()} · <t:{ts}:R>"
    return embed_template(
        "showcase",
        f"💎 Market Prices: {item_name}",
        f"[View on Warframe Market]({market_url})",
        category="economy",
        thumbnail=thumb,
        fields=fields,
        author=author,
        footer=footer,
        client=client,
    )


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

        from database import get_user_platform
        user_platform = await get_user_platform(interaction.guild.id, interaction.user.id) if interaction.guild else None
        platform_val = platform.value if platform else (user_platform or "pc")
        
        # Search for item
        item_data = await search_warframe_market_item(item, platform_val)
        
        if not item_data:
            hint = (
                "\n\nIf the bot runs on a server, the Warframe Market API may block requests. "
                "Set the **WARFRAME_MARKET_PROXY** (or **HTTPS_PROXY**) environment variable to an HTTP(S) proxy URL to try to bypass this."
            )

            async def on_retry_search(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                new_item = await search_warframe_market_item(item, platform_val)
                if not new_item:
                    return await btn_interaction.followup.send("Still unable to find item. Try again later.", ephemeral=True)
                new_price = await get_warframe_market_price(new_item.get("url_name", ""), platform_val)
                if not new_price:
                    return await btn_interaction.followup.send("Found item but could not fetch prices. Try again later.", ephemeral=True)
                emb = _build_trade_embed(new_item, new_price, platform_val, interaction.client, author=interaction.user, fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
                await btn_interaction.message.edit(embed=emb, view=None)

            return await interaction.followup.send(
                embed=error_embed(
                    "Item Not Found",
                    f"Could not find '{item}' on Warframe Market. Please check the spelling and try again.{hint}",
                    action_hint="Search manually at warframe.market and copy the exact item name.",
                    client=interaction.client,
                ),
                view=RetryView(on_retry_search),
                ephemeral=True,
            )
        
        item_name = item_data.get("item_name", item)
        item_url_name = item_data.get("url_name", "")
        
        # Get price data
        price_data = await get_warframe_market_price(item_url_name, platform_val)
        
        if not price_data:
            async def on_retry_price(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                new_price = await get_warframe_market_price(item_url_name, platform_val)
                if not new_price:
                    return await btn_interaction.followup.send("Still unable to fetch prices. Try again later.", ephemeral=True)
                emb = _build_trade_embed(item_data, new_price, platform_val, interaction.client, author=interaction.user, fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
                await btn_interaction.message.edit(embed=emb, view=None)

            return await interaction.followup.send(
                embed=error_embed(
                    "Price Data Unavailable",
                    f"Could not fetch price data for '{item_name}'. The item may not be tradeable or have no active listings.",
                    action_hint="Try again in a moment, or check warframe.market directly.",
                    client=interaction.client,
                ),
                view=RetryView(on_retry_price),
                ephemeral=True,
            )
        
        from datetime import datetime, timezone
        fetched_at = datetime.now(timezone.utc)
        embed = _build_trade_embed(item_data, price_data, platform_val, interaction.client, author=interaction.user, fetched_at=fetched_at)
        market_url = f"https://warframe.market/items/{item_url_name}"

        async def on_refresh(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            await btn_interaction.response.defer()
            invalidate(f"warframe_market:price:{item_url_name}:{platform_val}")
            new_price = await get_warframe_market_price(item_url_name, platform_val)
            if not new_price:
                return await btn_interaction.followup.send(
                    "Couldn't refresh prices right now. Warframe Market might be slow—try **Update data** again soon.",
                    ephemeral=True,
                )
            from datetime import datetime, timezone
            new_emb = _build_trade_embed(item_data, new_price, platform_val, interaction.client, author=interaction.user, fetched_at=datetime.now(timezone.utc))
            v2 = RefreshView(on_refresh, timeout=300)
            v2.add_item(discord.ui.Button(label="View on Warframe Market", url=market_url, style=discord.ButtonStyle.link, emoji="🔗"))
            await btn_interaction.message.edit(embed=new_emb, view=v2)

        v = RefreshView(on_refresh, timeout=300)
        v.add_item(discord.ui.Button(label="View on Warframe Market", url=market_url, style=discord.ButtonStyle.link, emoji="🔗"))
        await interaction.followup.send(embed=embed, view=v, ephemeral=True)
