"""List user's trading posts command."""
import discord
from discord import app_commands

from core.utils import obsidian_embed
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the trade_list and my_listings commands."""
    trade_decorator = group.command(name="trade_list", description="View your active trading listings.") if group else bot.tree.command(name="trade_list", description="View your active trading listings.")
    my_listings_decorator = group.command(name="my_listings", description="View your active trading listings (alias for trade_list).") if group else bot.tree.command(name="my_listings", description="View your active trading listings (alias for trade_list).")

    async def _list_listings_impl(interaction: discord.Interaction):
        """Shared implementation for listing user's active trading posts."""
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, listing_type, item_name, price, quantity, description, platform, status, created_at
                FROM trading_posts
                WHERE guild_id = ? AND user_id = ? AND status = 'ACTIVE'
                ORDER BY created_at DESC
            """, (interaction.guild.id, interaction.user.id))
            rows = await cur.fetchall()
        
        if not rows:
            from core.utils import empty_state_embed
            return await interaction.followup.send(
                embed=empty_state_embed(
                    "💼 No Active Listings",
                    "You don't have any active trading listings yet.",
                    suggestions=["trade", "trading trade_search"],
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed
        fields = []
        for listing_id, list_type, item_name, price, quantity, desc, plat, status, created_at in rows:
            value = f"**Type:** {list_type}\n"
            value += f"**Platform:** {plat.upper()}\n"
            if price:
                value += f"**Price:** {price}p\n"
            if quantity > 1:
                value += f"**Quantity:** {quantity}\n"
            if desc:
                value += f"**Details:** {desc[:100]}{'...' if len(desc) > 100 else ''}\n"
            value += f"**ID:** #{listing_id}"
            
            fields.append((f"{list_type}: {item_name}", value, False))
        
        embed = obsidian_embed(
            f"💼 Your Active Listings ({len(rows)})",
            "Use the buttons on your listing messages to manage them.",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @trade_decorator
    async def trade_list(interaction: discord.Interaction):
        """List user's active trading posts."""
        await _list_listings_impl(interaction)

    @my_listings_decorator
    async def my_listings(interaction: discord.Interaction):
        """List user's active trading listings (alias for trade_list)."""
        await _list_listings_impl(interaction)
