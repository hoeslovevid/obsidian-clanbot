"""Shop command - users can buy items with coins."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone, timedelta

from core.utils import obsidian_embed, feature_off_embed, bullet_list, ECONOMY_ENABLED
from database import DB_PATH, remove_coins, add_coins
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the shop command."""
    
    command_decorator = group.command(name="browse", description="View available items in the shop.") if group else bot.tree.command(name="browse", description="View available items in the shop.")
    
    @command_decorator
    async def shop(interaction: discord.Interaction):
        """View shop items."""
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
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
            cur2 = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur2.fetchone()
            balance = row[0] or 0 if row else 0
        
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
        
        item_type_emoji = {"role": "🎭", "coins": "💰", "xp": "⭐", "xp_boost": "⚡", "coin_boost": "💸", "custom": "🎁"}
        items = []
        for item_id, item_name, description, price, item_type, item_value, stock in rows[:15]:
            stock_text = f"({stock} left)" if stock >= 0 else "(Unlimited)"
            emoji = item_type_emoji.get(item_type, "📦")
            desc_short = description[:80] + ("..." if len(description) > 80 else "")
            items.append(f"{emoji} **{item_name}** — {price:,} coins {stock_text}\n   _{desc_short}_")
        items_text = bullet_list(items)
        if len(rows) > 15:
            items_text += f"\n_...and {len(rows) - 15} more_"
        
        bar_max = 100_000
        pct = min(100, int(100 * balance / bar_max)) if bar_max > 0 else 0
        bar_len = 8
        filled = int(bar_len * pct / 100)
        bar_str = "█" * filled + "░" * (bar_len - filled)
        balance_line = f"**{balance:,}** coins\n`[{bar_str}]` {pct}%"
        
        embed = obsidian_embed(
            "🛒 Shop",
            "Use `/store buy <item_name>` to purchase.",
            color=discord.Color.blue(),
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            fields=[
                ("💰 Your Balance", balance_line, True),
                ("📦 Items", items_text.strip()[:1024], False),
            ],
            footer=f"{len(rows)} item(s) • Use /store buy <item> to purchase",
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    command_decorator = group.command(name="buy", description="Purchase an item from the shop.") if group else bot.tree.command(name="buy", description="Purchase an item from the shop.")
    
    @command_decorator
    @app_commands.describe(item_name="Name of the item to buy")
    async def buy(interaction: discord.Interaction, item_name: str):
        """Buy an item from the shop."""
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
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
                WHERE guild_id=? AND item_name LIKE ? AND enabled=1
            """, (interaction.guild.id, f"%{item_name}%"))
            rows = await cur.fetchall()
            balance_row = None
            if rows:
                cur2 = await db.execute(
                    "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, interaction.user.id),
                )
                balance_row = await cur2.fetchone()
        
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Item Not Found",
                    f"No item found matching '{item_name}'. Use `/store browse` to see available items.",
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
        
        balance = balance_row[0] or 0 if balance_row else 0
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
        
        from datetime import datetime, timezone
        async with aiosqlite.connect(DB_PATH) as db:
            if stock > 0:
                await db.execute("UPDATE shop_items SET stock=stock-1 WHERE id=?", (item_id,))
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

        elif item_type == "xp_boost" and item_value:
            # item_value format: "multiplier:hours" e.g. "2:24" = 2x XP for 24 hours
            try:
                parts = item_value.split(":")
                multiplier = float(parts[0])
                hours = int(parts[1]) if len(parts) > 1 else 24
                expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
                from database import set_guild_setting, get_guild_setting
                # Stack with existing boost (take the higher one)
                existing = await get_guild_setting(interaction.guild.id, f"xp_boost:{interaction.user.id}")
                if existing:
                    try:
                        ex_mult, ex_exp = existing.split(":", 1)
                        ex_dt = datetime.fromisoformat(ex_exp)
                        if datetime.now(timezone.utc) < ex_dt and float(ex_mult) >= multiplier:
                            # Existing boost is still active and stronger — extend expiry only
                            new_expires = (max(ex_dt, datetime.now(timezone.utc)) + timedelta(hours=hours)).isoformat()
                            await set_guild_setting(interaction.guild.id, f"xp_boost:{interaction.user.id}", f"{ex_mult}:{new_expires}")
                            item_given = True
                        else:
                            await set_guild_setting(interaction.guild.id, f"xp_boost:{interaction.user.id}", f"{multiplier}:{expires_at}")
                            item_given = True
                    except Exception:
                        await set_guild_setting(interaction.guild.id, f"xp_boost:{interaction.user.id}", f"{multiplier}:{expires_at}")
                        item_given = True
                else:
                    await set_guild_setting(interaction.guild.id, f"xp_boost:{interaction.user.id}", f"{multiplier}:{expires_at}")
                    item_given = True
            except (ValueError, IndexError):
                pass

        elif item_type == "coin_boost" and item_value:
            # item_value format: "multiplier:hours" e.g. "1.5:12" = 1.5x coins for 12 hours
            try:
                parts = item_value.split(":")
                multiplier = float(parts[0])
                hours = int(parts[1]) if len(parts) > 1 else 24
                expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
                from database import set_guild_setting, get_guild_setting
                existing = await get_guild_setting(interaction.guild.id, f"coin_boost:{interaction.user.id}")
                if existing:
                    try:
                        ex_mult, ex_exp = existing.split(":", 1)
                        ex_dt = datetime.fromisoformat(ex_exp)
                        if datetime.now(timezone.utc) < ex_dt and float(ex_mult) >= multiplier:
                            new_expires = (max(ex_dt, datetime.now(timezone.utc)) + timedelta(hours=hours)).isoformat()
                            await set_guild_setting(interaction.guild.id, f"coin_boost:{interaction.user.id}", f"{ex_mult}:{new_expires}")
                            item_given = True
                        else:
                            await set_guild_setting(interaction.guild.id, f"coin_boost:{interaction.user.id}", f"{multiplier}:{expires_at}")
                            item_given = True
                    except Exception:
                        await set_guild_setting(interaction.guild.id, f"coin_boost:{interaction.user.id}", f"{multiplier}:{expires_at}")
                        item_given = True
                else:
                    await set_guild_setting(interaction.guild.id, f"coin_boost:{interaction.user.id}", f"{multiplier}:{expires_at}")
                    item_given = True
            except (ValueError, IndexError):
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
        elif item_type == "xp_boost":
            if item_given and item_value:
                try:
                    parts = item_value.split(":")
                    mult = float(parts[0])
                    hrs = int(parts[1]) if len(parts) > 1 else 24
                    desc += f"⚡ **{mult}x XP Boost** active for **{hrs} hours**!\n*All XP earned during this period is multiplied.*"
                except Exception:
                    desc += "⚡ XP Boost activated!"
            else:
                desc += "⚠️ XP Boost could not be applied. Please contact a moderator."
        elif item_type == "coin_boost":
            if item_given and item_value:
                try:
                    parts = item_value.split(":")
                    mult = float(parts[0])
                    hrs = int(parts[1]) if len(parts) > 1 else 24
                    desc += f"💸 **{mult}x Coin Boost** active for **{hrs} hours**!\n*All coins earned during this period are multiplied.*"
                except Exception:
                    desc += "💸 Coin Boost activated!"
            else:
                desc += "⚠️ Coin Boost could not be applied. Please contact a moderator."
        else:
            desc += "✅ Purchase successful! Your item will be delivered shortly."
        
        embed = obsidian_embed(
            "✅ Purchase Complete",
            desc,
            color=discord.Color.green(),
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
