"""Pet system commands."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timedelta, timezone

from utils import obsidian_embed
from database import DB_PATH, now_utc, get_user_balance, remove_coins, add_coins
import aiosqlite
import dateparser


def setup(bot, group=None):
    """Register pet commands."""
    
    command_decorator = group.command(name="pet_shop", description="View available pets to buy.") if group else bot.tree.command(name="pet_shop", description="View available pets to buy.")
    
    @command_decorator
    async def pet_shop(interaction: discord.Interaction):
        """View pet shop."""
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
        
        await interaction.response.defer()
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT pet_type, base_price, max_level, description FROM pet_types
                ORDER BY base_price
            """)
            pets = await cur.fetchall()
            
            if not pets:
                # Initialize default pets (must run inside same connection)
                default_pets = [
                    ("Dog", 100, 50, "A loyal companion"),
                    ("Cat", 150, 60, "An independent friend"),
                    ("Bird", 80, 40, "A cheerful winged friend"),
                    ("Fish", 75, 35, "A calm aquarium buddy"),
                    ("Rabbit", 120, 55, "A soft and speedy pal"),
                    ("Fox", 200, 70, "A clever and curious companion"),
                    ("Robot", 300, 80, "A mechanical companion"),
                    ("Wolf", 350, 85, "A fierce and loyal guardian"),
                    ("Dragon", 500, 100, "A powerful mythical creature"),
                    ("Phoenix", 600, 100, "A legendary fire bird that rises again"),
                ]
                for pet_type, price, max_level, desc in default_pets:
                    await db.execute("""
                        INSERT OR IGNORE INTO pet_types (pet_type, base_price, max_level, description)
                        VALUES (?, ?, ?, ?)
                    """, (pet_type, price, max_level, desc))
                await db.commit()
                cur = await db.execute("""
                    SELECT pet_type, base_price, max_level, description FROM pet_types
                    ORDER BY base_price
                """)
                pets = await cur.fetchall()
        
        shop_text = "\n".join([
            f"**{pet_type}** - {price} coins\n  {desc} (Max Level: {max_level})"
            for pet_type, price, max_level, desc in pets
        ])
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "🐾 Pet Shop",
                shop_text,
                color=discord.Color.gold(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="pet_buy", description="Buy a pet.") if group else bot.tree.command(name="pet_buy", description="Buy a pet.")
    
    @command_decorator
    @app_commands.describe(pet_type="Type of pet to buy", pet_name="Name for your pet")
    async def pet_buy(interaction: discord.Interaction, pet_type: str, pet_name: str):
        """Buy a pet."""
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
        
        await interaction.response.defer()
        
        # Check if user already has a pet
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT 1 FROM pets WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            if await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Have Pet",
                        "You already have a pet! Use `/pet` to view it.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    )
                )
            
            # Get pet type info
            cur = await db.execute("""
                SELECT base_price FROM pet_types WHERE pet_type=?
            """, (pet_type,))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Pet Type",
                        f"Pet type '{pet_type}' not found. Use `/pet_shop` to see available pets.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            price = row[0]
            balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            
            if balance < price:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Insufficient Funds",
                        f"You need {price} coins to buy a {pet_type}. You have {balance} coins.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            # Buy pet
            await remove_coins(interaction.guild.id, interaction.user.id, price, "PET", f"Purchased {pet_type} pet")
            
            await db.execute("""
                INSERT INTO pets (guild_id, user_id, pet_name, pet_type, level, experience, hunger, happiness, created_at)
                VALUES (?, ?, ?, ?, 1, 0, 100, 100, ?)
            """, (interaction.guild.id, interaction.user.id, pet_name, pet_type, now_utc().isoformat()))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Pet Purchased",
                f"You bought **{pet_name}** ({pet_type}) for {price} coins!\n\n"
                "Use `/pet` to view your pet, `/pet_feed` to feed it, and `/pet_play` to play with it.",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="pet", description="View your pet.") if group else bot.tree.command(name="pet", description="View your pet.")
    
    @command_decorator
    async def pet(interaction: discord.Interaction):
        """View pet."""
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
        
        await interaction.response.defer()
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT pet_name, pet_type, level, experience, hunger, happiness, last_fed_at, last_played_at
                FROM pets WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🐾 No Pet",
                    "You don't have a pet yet! Use `/pet_shop` to see available pets and `/pet_buy` to buy one.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
            )
        
        pet_name, pet_type, level, exp, hunger, happiness, last_fed, last_played = row
        
        # Calculate exp needed for next level (simple formula: level * 100)
        exp_needed = level * 100
        
        pet_text = f"**Name:** {pet_name}\n**Type:** {pet_type}\n**Level:** {level}\n"
        pet_text += f"**Experience:** {exp}/{exp_needed}\n"
        pet_text += f"**Hunger:** {hunger}/100 {'🍽️' if hunger < 50 else '✅'}\n"
        pet_text += f"**Happiness:** {happiness}/100 {'😢' if happiness < 50 else '😊'}\n"
        
        if last_fed:
            try:
                fed_time = dateparser.parse(last_fed, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if fed_time:
                    hours_since_fed = (datetime.now(timezone.utc) - fed_time).total_seconds() / 3600
                    pet_text += f"\n**Last Fed:** {int(hours_since_fed)} hours ago"
            except:
                pass
        
        await interaction.followup.send(
            embed=obsidian_embed(
                f"🐾 {pet_name}",
                pet_text,
                color=discord.Color.gold(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="pet_feed", description="Feed your pet (costs 10 coins).") if group else bot.tree.command(name="pet_feed", description="Feed your pet (costs 10 coins).")
    
    @command_decorator
    async def pet_feed(interaction: discord.Interaction):
        """Feed pet."""
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
        
        await interaction.response.defer()
        
        cost = 10
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        if balance < cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {cost} coins to feed your pet. You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT hunger FROM pets WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Pet",
                        "You don't have a pet! Use `/pet_buy` to buy one.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            hunger = min(100, row[0] + 20)  # Increase hunger by 20, max 100
            
            await remove_coins(interaction.guild.id, interaction.user.id, cost, "PET", "Pet food")
            await db.execute("""
                UPDATE pets SET hunger=?, last_fed_at=? WHERE guild_id=? AND user_id=?
            """, (hunger, now_utc().isoformat(), interaction.guild.id, interaction.user.id))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "🍽️ Pet Fed",
                f"Your pet has been fed! Hunger: {hunger}/100",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="pet_play", description="Play with your pet (costs 5 coins).") if group else bot.tree.command(name="pet_play", description="Play with your pet (costs 5 coins).")
    
    @command_decorator
    async def pet_play(interaction: discord.Interaction):
        """Play with pet."""
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
        
        await interaction.response.defer()
        
        cost = 5
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        if balance < cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {cost} coins to play with your pet. You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT happiness, experience, level FROM pets WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Pet",
                        "You don't have a pet! Use `/pet_buy` to buy one.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            happiness, exp, level = row
            happiness = min(100, happiness + 15)  # Increase happiness by 15
            exp += 10  # Gain experience
            
            # Check for level up
            exp_needed = level * 100
            new_level = level
            if exp >= exp_needed:
                new_level = level + 1
                exp = 0  # Reset exp on level up
            
            await remove_coins(interaction.guild.id, interaction.user.id, cost, "PET", "Play with pet")
            await db.execute("""
                UPDATE pets SET happiness=?, experience=?, level=?, last_played_at=?
                WHERE guild_id=? AND user_id=?
            """, (happiness, exp, new_level, now_utc().isoformat(), interaction.guild.id, interaction.user.id))
            await db.commit()
        
        level_up_text = f"\n🎉 **Level Up!** Your pet is now level {new_level}!" if new_level > level else ""
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "🎮 Played with Pet",
                f"Your pet had fun! Happiness: {happiness}/100{level_up_text}",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )
