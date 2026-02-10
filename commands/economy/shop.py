"""Shop command - users can buy items with coins."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, ECONOMY_ENABLED
from database import DB_PATH, remove_coins, add_coins, get_user_balance
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the shop command."""
    
    command_decorator = group.command(name="browse", description="View available items in the shop.") if group else bot.tree.command(name="browse", description="View available items in the shop.")
    
    @command_decorator
    async def shop(interaction: discord.Interaction):
        """View shop items."""
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Economy Disabled",
                    "The economy system is currently disabled.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
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
                SELECT id, item_name, description, price, item_type, item_value, stock
                FROM shop_items
                WHERE guild_id=? AND enabled=1
                ORDER BY price ASC
            """, (interaction.guild.id,))
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🛒 Shop",
                    "No items available in the shop at the moment. Check back later!",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        desc = ""
        for item_id, item_name, description, price, item_type, item_value, stock in rows:
            stock_text = f"({stock} left)" if stock >= 0 else "(Unlimited)"
            item_type_emoji = {
                "role": "🎭",
                "coins": "💰",
                "xp": "⭐",
                "custom": "🎁",
            }.get(item_type, "📦")
            
            desc += f"{item_type_emoji} **{item_name}** - {price:,} coins {stock_text}\n"
            desc += f"   {description}\n\n"
        
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        embed = obsidian_embed(
            "🛒 Shop",
            desc[:4000],
            color=discord.Color.blue(),
            client=interaction.client,
        )
        embed.set_footer(text=f"Your balance: {balance:,} coins • Use /buy to purchase items")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    command_decorator = group.command(name="buy", description="Purchase an item from the shop.") if group else bot.tree.command(name="buy", description="Purchase an item from the shop.")
    
    @command_decorator
    @app_commands.describe(item_name="Name of the item to buy")
    async def buy(interaction: discord.Interaction, item_name: str):
        """Buy an item from the shop."""
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Economy Disabled",
                    "The economy system is currently disabled.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
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
        
        # Find item
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, item_name, description, price, item_type, item_value, stock
                FROM shop_items
                WHERE guild_id=? AND item_name LIKE ? AND enabled=1
            """, (interaction.guild.id, f"%{item_name}%"))
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Item Not Found",
                    f"No item found matching '{item_name}'. Use `/economy store browse` to see available items.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # If multiple matches, use exact match if available, otherwise use first
        item = None
        for row in rows:
            if row[1].lower() == item_name.lower():
                item = row
                break
        if not item:
            item = rows[0]
        
        item_id, item_name, description, price, item_type, item_value, stock = item
        
        # Check stock
        if stock == 0:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Out of Stock",
                    f"**{item_name}** is currently out of stock.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check balance
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        if balance < price:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Balance",
                    f"You need {price:,} coins to buy **{item_name}**, but you only have {balance:,} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Process purchase
        success = await remove_coins(
            interaction.guild.id,
            interaction.user.id,
            price,
            "SHOP_PURCHASE",
            f"Purchased: {item_name}"
        )
        
        if not success:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Transaction Failed",
                    "Failed to process purchase. Please try again.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Update stock if limited
        if stock > 0:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE shop_items SET stock=stock-1 WHERE id=?
                """, (item_id,))
                await db.commit()
        
        # Record purchase
        from datetime import datetime, timezone
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO user_purchases (guild_id, user_id, item_id, item_name, price_paid, purchased_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                interaction.guild.id,
                interaction.user.id,
                item_id,
                item_name,
                price,
                datetime.now(timezone.utc).isoformat()
            ))
            await db.commit()
        
        # Give item
        item_given = False
        if item_type == "role" and item_value:
            try:
                role_id = int(item_value)
                role = interaction.guild.get_role(role_id)
                if role and isinstance(interaction.user, discord.Member):
                    if role not in interaction.user.roles:
                        await interaction.user.add_roles(role, reason=f"Purchased from shop: {item_name}")
                        item_given = True
                    else:
                        item_given = True  # Already has role
            except (ValueError, discord.Forbidden):
                pass
        
        elif item_type == "coins" and item_value:
            try:
                coins = int(item_value)
                await add_coins(interaction.guild.id, interaction.user.id, coins, "SHOP_REWARD", f"Item: {item_name}")
                item_given = True
            except ValueError:
                pass
        
        elif item_type == "xp" and item_value:
            try:
                from database import add_xp
                xp = int(item_value)
                await add_xp(interaction.guild.id, interaction.user.id, xp, f"SHOP_{item_name}")
                item_given = True
            except ValueError:
                pass
        
        desc = f"**Item:** {item_name}\n"
        desc += f"**Price:** {price:,} coins\n"
        desc += f"**Type:** {item_type.replace('_', ' ').title()}\n\n"
        
        if item_type == "role":
            if item_given:
                desc += "✅ Role has been added to your account!"
            else:
                desc += "⚠️ Role could not be added. Please contact a moderator."
        elif item_type == "coins":
            if item_given:
                desc += f"✅ {item_value} coins have been added to your balance!"
            else:
                desc += "⚠️ Coins could not be added. Please contact a moderator."
        elif item_type == "xp":
            if item_given:
                desc += f"✅ {item_value} XP has been added to your account!"
            else:
                desc += "⚠️ XP could not be added. Please contact a moderator."
        else:
            desc += "✅ Purchase successful! Your item will be delivered shortly."
        
        embed = obsidian_embed(
            "✅ Purchase Complete",
            desc,
            color=discord.Color.green(),
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
