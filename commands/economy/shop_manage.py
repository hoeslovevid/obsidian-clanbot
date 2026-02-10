"""Shop management command - moderators can add/remove shop items."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, ECONOMY_ENABLED, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the shop_manage command."""
    
    command_decorator = group.command(name="manage", description="Manage shop items (moderators only).") if group else bot.tree.command(name="manage", description="Manage shop items (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        item_name="Name of the item",
        description="Description of the item",
        price="Price in coins",
        item_type="Type of item",
        item_value="Value for the item (role ID, coin amount, XP amount, etc.)",
        stock="Stock amount (-1 for unlimited)"
    )
    @app_commands.choices(item_type=[
        app_commands.Choice(name="Role", value="role"),
        app_commands.Choice(name="Coins", value="coins"),
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="Custom", value="custom"),
    ])
    async def shop_manage(
        interaction: discord.Interaction,
        action: str,
        item_name: Optional[str] = None,
        description: Optional[str] = None,
        price: Optional[int] = None,
        item_type: Optional[app_commands.Choice[str]] = None,
        item_value: Optional[str] = None,
        stock: Optional[int] = None
    ):
        """Manage shop items."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
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
        
        if action.lower() == "add":
            if not all([item_name, description, price, item_type]):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameters",
                        "Please provide item_name, description, price, and item_type.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            if price < 1:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Price",
                        "Price must be at least 1 coin.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Validate item_type specific requirements
            if item_type.value == "role" and not item_value:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Role ID",
                        "Role items require item_value to be a role ID.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            stock_value = stock if stock is not None else -1
            
            from datetime import datetime, timezone
            async with aiosqlite.connect(DB_PATH) as db:
                try:
                    await db.execute("""
                        INSERT INTO shop_items 
                        (guild_id, item_name, description, price, item_type, item_value, stock, enabled, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """, (
                        interaction.guild.id,
                        item_name,
                        description,
                        price,
                        item_type.value,
                        item_value or "",
                        stock_value,
                        datetime.now(timezone.utc).isoformat()
                    ))
                    await db.commit()
                except aiosqlite.IntegrityError:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Item Exists",
                            f"An item with the name '{item_name}' already exists. Use 'update' to modify it or 'remove' to delete it.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
            
            fields = [
                ("Item", item_name, True),
                ("Description", description[:1024], False),
                ("Price", f"{price:,} coins", True),
                ("Type", item_type.value.replace('_', ' ').title(), True),
                ("Stock", "Unlimited" if stock_value == -1 else str(stock_value), True),
            ]
            if item_value:
                fields.insert(4, ("Value", item_value[:1024], True))
            embed = obsidian_embed(
                "✅ Item Added",
                "",
                color=discord.Color.green(),
                fields=fields,
                thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
                footer="Use action:Remove to delete from shop",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        elif action.lower() == "remove":
            if not item_name:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameter",
                        "Please provide item_name to remove.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id FROM shop_items
                    WHERE guild_id=? AND item_name LIKE ?
                """, (interaction.guild.id, f"%{item_name}%"))
                row = await cur.fetchone()
                
                if not row:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Item Not Found",
                            f"No item found matching '{item_name}'.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    UPDATE shop_items SET enabled=0 WHERE id=?
                """, (row[0],))
                await db.commit()
            
            embed = obsidian_embed(
                "✅ Item Removed",
                f"Item '{item_name}' has been removed from the shop.",
                color=discord.Color.green(),
                thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
                footer="Item disabled; can be re-enabled via database",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        elif action.lower() == "restock":
            if not item_name or stock is None:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameters",
                        "Please provide item_name and stock amount.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id FROM shop_items
                    WHERE guild_id=? AND item_name LIKE ?
                """, (interaction.guild.id, f"%{item_name}%"))
                row = await cur.fetchone()
                
                if not row:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Item Not Found",
                            f"No item found matching '{item_name}'.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    UPDATE shop_items SET stock=? WHERE id=?
                """, (stock, row[0]))
                await db.commit()
            
            embed = obsidian_embed(
                "✅ Stock Updated",
                f"Stock for '{item_name}' has been set to {stock if stock >= 0 else 'Unlimited'}.",
                color=discord.Color.green(),
                thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
                footer=f"Item: {item_name}",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        elif action.lower() == "list":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, item_name, description, price, item_type, item_value, stock, enabled
                    FROM shop_items
                    WHERE guild_id=?
                    ORDER BY enabled DESC, price ASC
                """, (interaction.guild.id,))
                rows = await cur.fetchall()
            
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Shop Items",
                        "No items in the shop.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            desc = ""
            for item_id, item_name, description, price, item_type, item_value, stock, enabled in rows:
                status = "✅" if enabled else "❌"
                stock_text = f"({stock} left)" if stock >= 0 else "(Unlimited)"
                desc += f"{status} **{item_name}** - {price:,} coins {stock_text}\n"
                desc += f"   {description}\n\n"
            
            embed = obsidian_embed(
                "📋 Shop Items",
                desc[:4000],
                color=discord.Color.blue(),
                thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
                footer=f"{len(rows)} item(s) • Use action:Add/Remove/Restock to manage",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Action",
                    "Valid actions: `add`, `remove`, `restock`, `list`",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
