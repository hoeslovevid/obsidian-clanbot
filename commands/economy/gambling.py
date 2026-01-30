"""Gambling games commands."""
import discord
from discord import app_commands
from typing import Optional
import random

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc, get_user_balance, add_coins, remove_coins
import aiosqlite


def setup(bot, group=None):
    """Register gambling commands."""
    
    command_decorator = group.command(name="slots", description="Play slots! (Cost: 50 coins)") if group else bot.tree.command(name="slots", description="Play slots! (Cost: 50 coins)")
    
    @command_decorator
    async def slots(interaction: discord.Interaction):
        """Play a slot machine game."""
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
        
        cost = 50
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        if balance < cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {cost} coins to play slots. You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        # Remove coins
        await remove_coins(interaction.guild.id, interaction.user.id, cost, "GAMBLING", "Slots spin")
        
        # Spin slots
        symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "7️⃣"]
        reel1 = random.choice(symbols)
        reel2 = random.choice(symbols)
        reel3 = random.choice(symbols)
        
        # Calculate winnings
        winnings = 0
        if reel1 == reel2 == reel3:
            if reel1 == "💎":
                winnings = 1000
            elif reel1 == "7️⃣":
                winnings = 500
            elif reel1 == "⭐":
                winnings = 300
            else:
                winnings = 200
        elif reel1 == reel2 or reel2 == reel3 or reel1 == reel3:
            winnings = 50
        
        # Add winnings
        if winnings > 0:
            await add_coins(interaction.guild.id, interaction.user.id, winnings)
            new_balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            result = f"**🎉 You won {winnings} coins!**\n**New Balance:** {new_balance} coins"
            color = discord.Color.gold()
        else:
            new_balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            result = f"**Better luck next time!**\n**New Balance:** {new_balance} coins"
            color = discord.Color.red()
        
        # Log gambling
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO gambling_history (guild_id, user_id, game_type, bet_amount, win_amount, result, created_at)
                VALUES (?, ?, 'slots', ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, cost, winnings, "win" if winnings > 0 else "loss", now_utc().isoformat()))
            await db.commit()
        
        embed = obsidian_embed(
            "🎰 Slots",
            f"**{reel1} | {reel2} | {reel3}**\n\n{result}",
            color=color,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
    
    command_decorator = group.command(name="dice", description="Roll dice! Bet coins and try to roll higher than the bot.") if group else bot.tree.command(name="dice", description="Roll dice! Bet coins and try to roll higher than the bot.")
    
    @command_decorator
    @app_commands.describe(bet="Amount of coins to bet")
    async def dice(interaction: discord.Interaction, bet: int):
        """Play dice game."""
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
        
        if bet < 1:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Bet",
                    "Bet must be at least 1 coin.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        if balance < bet:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {bet} coins to play. You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        # Remove coins
        await remove_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", "Dice roll")
        
        # Roll dice
        user_roll = random.randint(1, 6)
        bot_roll = random.randint(1, 6)
        
        # Calculate winnings
        if user_roll > bot_roll:
            winnings = bet * 2
            await add_coins(interaction.guild.id, interaction.user.id, winnings)
            result = f"**🎉 You won!**\n**Your roll:** {user_roll}\n**Bot roll:** {bot_roll}\n**Winnings:** {winnings} coins"
            color = discord.Color.green()
            win_amount = winnings
            game_result = "win"
        elif user_roll < bot_roll:
            result = f"**You lost!**\n**Your roll:** {user_roll}\n**Bot roll:** {bot_roll}\n**Lost:** {bet} coins"
            color = discord.Color.red()
            win_amount = 0
            game_result = "loss"
        else:
            # Tie - return bet
            await add_coins(interaction.guild.id, interaction.user.id, bet)
            result = f"**It's a tie!**\n**Your roll:** {user_roll}\n**Bot roll:** {bot_roll}\n**Bet returned:** {bet} coins"
            color = discord.Color.orange()
            win_amount = bet
            game_result = "tie"
        
        new_balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        # Log gambling
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO gambling_history (guild_id, user_id, game_type, bet_amount, win_amount, result, created_at)
                VALUES (?, ?, 'dice', ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, bet, win_amount, game_result, now_utc().isoformat()))
            await db.commit()
        
        embed = obsidian_embed(
            "🎲 Dice",
            f"{result}\n**New Balance:** {new_balance} coins",
            color=color,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
    
    command_decorator = group.command(name="roulette", description="Play roulette! Bet on red, black, or green.") if group else bot.tree.command(name="roulette", description="Play roulette! Bet on red, black, or green.")
    
    @command_decorator
    @app_commands.describe(bet="Amount of coins to bet", color="Color to bet on (red/black/green)")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red", value="red"),
        app_commands.Choice(name="Black", value="black"),
        app_commands.Choice(name="Green", value="green"),
    ])
    async def roulette(interaction: discord.Interaction, bet: int, color: str):
        """Play roulette game."""
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
        
        if bet < 1:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Bet",
                    "Bet must be at least 1 coin.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        if balance < bet:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {bet} coins to play. You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        # Remove coins
        await remove_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", "Roulette bet")
        
        # Spin roulette (0-36, 0 is green)
        number = random.randint(0, 36)
        
        # Determine color
        if number == 0:
            landed_color = "green"
        elif number in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]:
            landed_color = "red"
        else:
            landed_color = "black"
        
        # Calculate winnings
        if color == landed_color:
            if color == "green":
                winnings = bet * 35  # Green pays 35:1
            else:
                winnings = bet * 2  # Red/Black pays 2:1
            await add_coins(interaction.guild.id, interaction.user.id, winnings)
            result = f"**🎉 You won!**\n**Landed on:** {landed_color.capitalize()} ({number})\n**Winnings:** {winnings} coins"
            color_emoji = discord.Color.green()
            win_amount = winnings
            game_result = "win"
        else:
            result = f"**You lost!**\n**Landed on:** {landed_color.capitalize()} ({number})\n**Lost:** {bet} coins"
            color_emoji = discord.Color.red()
            win_amount = 0
            game_result = "loss"
        
        new_balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        # Log gambling
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO gambling_history (guild_id, user_id, game_type, bet_amount, win_amount, result, created_at)
                VALUES (?, ?, 'roulette', ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, bet, win_amount, game_result, now_utc().isoformat()))
            await db.commit()
        
        embed = obsidian_embed(
            "🎰 Roulette",
            f"{result}\n**New Balance:** {new_balance} coins",
            color=color_emoji,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
