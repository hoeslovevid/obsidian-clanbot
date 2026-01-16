"""Search trading listings command."""
import discord
from discord import app_commands

from utils import obsidian_embed
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot):
    """Register the trade_search command."""
    @bot.tree.command(name="trade_search", description="Search active trading listings.")
    @app_commands.describe(
        query="Search term (item name, user, etc.)",
        listing_type="Filter by listing type",
        platform="Filter by platform",
        limit="Number of results (default: 10, max: 25)"
    )
    @app_commands.choices(listing_type=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="WTS - Want To Sell", value="WTS"),
        app_commands.Choice(name="WTB - Want To Buy", value="WTB"),
    ])
    @app_commands.choices(platform=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="PC", value="pc"),
        app_commands.Choice(name="Xbox", value="xbox"),
        app_commands.Choice(name="PlayStation", value="ps4"),
        app_commands.Choice(name="Switch", value="switch"),
    ])
    async def trade_search(
        interaction: discord.Interaction,
        query: str = None,
        listing_type: app_commands.Choice[str] = None,
        platform: app_commands.Choice[str] = None,
        limit: int = 10
    ):
        """Search trading listings."""
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
        
        await interaction.response.defer(ephemeral=True)
        
        if limit < 1 or limit > 25:
            limit = 10
        
        type_filter = listing_type.value if listing_type and listing_type.value != "all" else None
        platform_filter = platform.value if platform and platform.value != "all" else None
        
        # Build query
        async with aiosqlite.connect(DB_PATH) as db:
            sql = """
                SELECT id, user_id, listing_type, item_name, price, quantity, description, platform, created_at
                FROM trading_posts
                WHERE guild_id = ? AND status = 'ACTIVE'
            """
            params = [interaction.guild.id]
            
            if type_filter:
                sql += " AND listing_type = ?"
                params.append(type_filter)
            
            if platform_filter:
                sql += " AND platform = ?"
                params.append(platform_filter)
            
            if query:
                sql += " AND (item_name LIKE ? OR description LIKE ?)"
                params.extend([f"%{query}%", f"%{query}%"])
            
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cur = await db.execute(sql, params)
            rows = await cur.fetchall()
        
        if not rows:
            filters = []
            if query:
                filters.append(f"query: '{query}'")
            if type_filter:
                filters.append(f"type: {type_filter}")
            if platform_filter:
                filters.append(f"platform: {platform_filter.upper()}")
            
            filter_text = f" with filters ({', '.join(filters)})" if filters else ""
            
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "💼 No Listings Found",
                    f"No active listings found{filter_text}.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed
        fields = []
        for listing_id, user_id, list_type, item_name, price, quantity, desc, plat, created_at in rows:
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            
            value = f"**Type:** {list_type}\n"
            value += f"**By:** {username}\n"
            value += f"**Platform:** {plat.upper()}\n"
            if price:
                value += f"**Price:** {price}p\n"
            if quantity > 1:
                value += f"**Quantity:** {quantity}\n"
            value += f"**ID:** #{listing_id}"
            
            fields.append((f"{list_type}: {item_name}", value, False))
        
        embed = obsidian_embed(
            f"💼 Trading Listings ({len(rows)} found)",
            f"Use `/trade_price <item>` to check market prices.",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
