"""Pet system commands."""
import discord  # type: ignore
from discord import app_commands  # type: ignore
from typing import Optional
from datetime import datetime, timedelta, timezone

from utils import obsidian_embed
from database import DB_PATH, now_utc, get_user_balance, remove_coins, add_coins
import aiosqlite
import dateparser

# Pet images: Twemoji CDN icons + Wikimedia Commons photos for embed visualization
# Format: (thumbnail_icon_url, large_image_url)
PET_IMAGES = {
    "Dog": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f436.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/2/26/YellowLabradorLooking_new.jpg/640px-YellowLabradorLooking_new.jpg"),
    "Cat": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f431.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/640px-Cat03.jpg"),
    "Bird": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f426.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b6/Bengalese_Finch.jpg/640px-Bengalese_Finch.jpg"),
    "Fish": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f41f.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/Georgia_Aquarium_-_Giant_Grouper.jpg/640px-Georgia_Aquarium_-_Giant_Grouper.jpg"),
    "Rabbit": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f430.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1f/Oryctolagus_cuniculus_Rcdo.jpg/640px-Oryctolagus_cuniculus_Rcdo.jpg"),
    "Fox": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f98a.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/4/43/Red_Fox_in_Blijdorp_Zoo.jpg/640px-Red_Fox_in_Blijdorp_Zoo.jpg"),
    "Robot": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f916.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Atlas_from_Boston_Dynamics.jpg/640px-Atlas_from_Boston_Dynamics.jpg"),
    "Wolf": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f43a.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5f/Kolm%C3%A5rden_Wolf.jpg/640px-Kolm%C3%A5rden_Wolf.jpg"),
    "Dragon": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f409.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/Bearded_dragon.jpg/640px-Bearded_dragon.jpg"),
    "Phoenix": ("https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f525.png", "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4e/Ph%C3%B6nix-pavlensky-2.jpg/640px-Ph%C3%B6nix-pavlensky-2.jpg"),
}

# Pet leveling constants
EXP_PER_LEVEL = 75  # XP needed = level * EXP_PER_LEVEL (e.g. 75 for L1->L2, 150 for L2->L3)
EXP_FEED = 8
EXP_PLAY = 15

# Decay: hunger and happiness decrease over time when not tended
HUNGER_DECAY_PER_HOUR = 5
HAPPINESS_DECAY_PER_HOUR = 3


def _exp_needed_for_level(level: int) -> int:
    """XP required to level up from current level to next."""
    return level * EXP_PER_LEVEL


def _apply_decay(
    current: int,
    last_action_at: Optional[str],
    created_at: str,
    decay_per_hour: int,
) -> int:
    """Compute effective value after decay since last action. Uses created_at if last_action_at is None."""
    ref = last_action_at or created_at
    try:
        ref_time = dateparser.parse(ref, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
        if ref_time:
            hours = (datetime.now(timezone.utc) - ref_time).total_seconds() / 3600
            decayed = current - int(hours * decay_per_hour)
            return max(0, min(100, decayed))
    except Exception:
        pass
    return current


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
        
        # Build multiple embeds: one per pet with thumbnail and refined layout
        embeds = []
        for pet_type, price, max_level, desc in pets:
            icon_url, image_url = PET_IMAGES.get(pet_type, (None, None))
            if not icon_url:
                icon_url = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f43e.png"  # paw prints fallback
            
            e = discord.Embed(
                title=f"🐾 {pet_type}",
                description=desc,
                color=discord.Color.gold(),
            )
            e.add_field(name="💰 Price", value=f"**{price:,}** coins", inline=True)
            e.add_field(name="📈 Max Level", value=str(max_level), inline=True)
            e.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
            e.set_thumbnail(url=icon_url)
            if image_url:
                e.set_image(url=image_url)
            e.set_footer(text=f"Use /pet_buy • Choose \"{pet_type}\" as pet type")
            embeds.append(e)
        
        # Discord allows 10 embeds per message
        await interaction.followup.send(
            embeds=embeds[:10],
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
                SELECT p.pet_name, p.pet_type, p.level, p.experience, p.hunger, p.happiness,
                       p.last_fed_at, p.last_played_at, p.created_at, pt.max_level
                FROM pets p
                JOIN pet_types pt ON p.pet_type = pt.pet_type
                WHERE p.guild_id=? AND p.user_id=?
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
        
        pet_name, pet_type, level, exp, hunger, happiness, last_fed, last_played, created_at, max_level = row
        
        # Apply decay for display (hunger/happiness decrease over time)
        hunger = _apply_decay(hunger, last_fed, created_at, HUNGER_DECAY_PER_HOUR)
        happiness = _apply_decay(happiness, last_played, created_at, HAPPINESS_DECAY_PER_HOUR)
        
        exp_needed = _exp_needed_for_level(level)
        pet_text = f"**Name:** {pet_name}\n**Type:** {pet_type}\n**Level:** {level} / {max_level}\n"
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
                SELECT p.hunger, p.experience, p.level, p.pet_type, p.last_fed_at, p.created_at, pt.max_level
                FROM pets p
                JOIN pet_types pt ON p.pet_type = pt.pet_type
                WHERE p.guild_id=? AND p.user_id=?
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
            
            hunger, exp, level, pet_type, last_fed_at, created_at, max_level = row
            hunger = _apply_decay(hunger, last_fed_at, created_at, HUNGER_DECAY_PER_HOUR)
            hunger = min(100, hunger + 20)  # Increase hunger by 20, max 100
            exp = exp + EXP_FEED
            
            # Level-up logic (cap at max_level)
            new_level = level
            while new_level < max_level and exp >= _exp_needed_for_level(new_level):
                exp -= _exp_needed_for_level(new_level)
                new_level += 1
            
            await remove_coins(interaction.guild.id, interaction.user.id, cost, "PET", "Pet food")
            await db.execute("""
                UPDATE pets SET hunger=?, experience=?, level=?, last_fed_at=? WHERE guild_id=? AND user_id=?
            """, (hunger, exp, new_level, now_utc().isoformat(), interaction.guild.id, interaction.user.id))
            await db.commit()
        
        level_up_text = f"\n🎉 **Level Up!** Your pet is now level {new_level}!" if new_level > level else ""
        await interaction.followup.send(
            embed=obsidian_embed(
                "🍽️ Pet Fed",
                f"Your pet has been fed! Hunger: {hunger}/100{level_up_text}",
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
                SELECT p.happiness, p.experience, p.level, p.last_played_at, p.created_at, pt.max_level
                FROM pets p
                JOIN pet_types pt ON p.pet_type = pt.pet_type
                WHERE p.guild_id=? AND p.user_id=?
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
            
            happiness, exp, level, last_played_at, created_at, max_level = row
            happiness = _apply_decay(happiness, last_played_at, created_at, HAPPINESS_DECAY_PER_HOUR)
            happiness = min(100, happiness + 15)  # Increase happiness by 15
            exp = exp + EXP_PLAY  # Gain experience
            
            # Level-up logic (cap at max_level, carry over excess exp)
            new_level = level
            while new_level < max_level and exp >= _exp_needed_for_level(new_level):
                exp -= _exp_needed_for_level(new_level)
                new_level += 1
            
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
