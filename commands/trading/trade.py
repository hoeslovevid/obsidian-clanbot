"""Trading post command for posting WTS/WTB listings."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from core.utils import obsidian_embed
from database import DB_PATH, now_utc
from api.warframe_api import search_warframe_market_item, get_warframe_market_price
from commands.trading.trade_price import item_autocomplete
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the trade command."""
    command_decorator = group.command(name="trade", description="Post WTS/WTB listing — platinum items, Warframe market prices.") if group else bot.tree.command(name="trade", description="Post a WTS or WTB trading listing.")
    
    @command_decorator
    @app_commands.autocomplete(item=item_autocomplete)
    @app_commands.describe(
        listing_type="Type of listing",
        item="Item name (e.g., 'Mesa Prime Set', 'Primed Continuity')",
        price="Price in platinum (optional for WTB)",
        quantity="Quantity (default: 1)",
        description="Additional details (optional)",
        platform="Platform (default: PC)"
    )
    @app_commands.choices(listing_type=[
        app_commands.Choice(name="WTS - Want To Sell", value="WTS"),
        app_commands.Choice(name="WTB - Want To Buy", value="WTB"),
    ])
    @app_commands.choices(platform=[
        app_commands.Choice(name="PC", value="pc"),
        app_commands.Choice(name="Xbox", value="xbox"),
        app_commands.Choice(name="PlayStation", value="ps4"),
        app_commands.Choice(name="Switch", value="switch"),
    ])
    async def trade(
        interaction: discord.Interaction,
        listing_type: app_commands.Choice[str],
        item: str,
        price: int = None,
        quantity: int = 1,
        description: str = None,
        platform: app_commands.Choice[str] = None
    ):
        """Post a trading listing."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        from core.utils import feature_enabled, feature_off_embed  # Item 85
        if not await feature_enabled(interaction.guild.id, "trade"):
            return await interaction.response.send_message(embed=feature_off_embed("Trading", client=interaction.client), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        listing_type_val = listing_type.value
        platform_val = platform.value if platform else "pc"
        
        # Validate price for WTS
        if listing_type_val == "WTS" and price is None:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Price Required",
                    "WTS listings require a price. Use `/trade_price` to check current market prices.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if price is not None and price < 1:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Price",
                    "Price must be at least 1 platinum.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if quantity < 1:
            quantity = 1
        
        # Get trading channel
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT channel_id FROM trading_channel_settings WHERE guild_id = ?
            """, (interaction.guild.id,))
            row = await cur.fetchone()
        
        trading_channel = None
        if row and row[0]:
            trading_channel = interaction.guild.get_channel(row[0])
        
        # If no trading channel set, use current channel
        if not trading_channel or not isinstance(trading_channel, discord.TextChannel):
            trading_channel = interaction.channel
            if not isinstance(trading_channel, discord.TextChannel):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Channel",
                        "Please use this command in a text channel.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        # Try to get price info from Warframe Market for reference
        price_info = None
        try:
            item_data = await search_warframe_market_item(item, platform_val)
            if item_data:
                item_url_name = item_data.get("url_name", "")
                if item_url_name:
                    price_info = await get_warframe_market_price(item_url_name, platform_val)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not fetch price info: {e}")
        
        # Create listing
        from datetime import timedelta
        created_at = now_utc().isoformat()
        expires_at = (now_utc() + timedelta(days=14)).isoformat()
        listing_id = None
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO trading_posts (guild_id, user_id, listing_type, item_name, price, quantity, description, status, created_at, platform, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, listing_type_val, item, price, quantity, description, created_at, platform_val, expires_at))
            await db.commit()
            
            cur = await db.execute("SELECT last_insert_rowid()")
            listing_id = (await cur.fetchone())[0]
        
        if not listing_id:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Failed to create listing. Please try again.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed
        fields = [
            ("Item", item, True),
            ("Type", listing_type_val, True),
            ("Platform", platform_val.upper(), True),
        ]
        
        if price:
            fields.append(("Price", f"{price} platinum", True))
        
        if quantity > 1:
            fields.append(("Quantity", str(quantity), True))
        
        if description:
            fields.append(("Details", description, False))
        
        # Add market price comparison if available
        if price_info:
            market_info = []
            if price_info.get("lowest_sell"):
                market_info.append(f"**Lowest Sell:** {price_info['lowest_sell']}p")
            if price_info.get("highest_buy"):
                market_info.append(f"**Highest Buy:** {price_info['highest_buy']}p")
            
            if market_info:
                fields.append(("Market Prices", "\n".join(market_info), False))
        
        fields.append(("Listing ID", f"#{listing_id}", True))
        try:
            from datetime import datetime, timezone as _tz
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            exp_ts = int(exp_dt.timestamp())
            fields.append(("Expires", f"<t:{exp_ts}:R>", True))
        except Exception:
            pass
        
        color = discord.Color.green() if listing_type_val == "WTS" else discord.Color.blue()
        
        embed = obsidian_embed(
            f"💼 {listing_type_val}: {item}",
            f"Posted by {interaction.user.mention}",
            color=color,
            author=interaction.user,
            fields=fields,
            client=interaction.client,
        )
        
        # Create view for managing the listing
        from views import TradingPostView
        view = TradingPostView(listing_id, interaction.user.id)
        bot.add_view(view)
        
        try:
            message = await trading_channel.send(embed=embed, view=view)
            
            # Update message_id
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE trading_posts SET message_id = ?, channel_id = ? WHERE id = ?
                """, (message.id, trading_channel.id, listing_id))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Listing Posted",
                    f"Your {listing_type_val} listing has been posted in {trading_channel.mention}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    f"I don't have permission to send messages in {trading_channel.mention}.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error posting trade listing: {e}")
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    f"Failed to post listing: {str(e)}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
