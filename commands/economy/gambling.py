"""Gambling games commands."""
import discord
from discord import app_commands
from typing import Optional
import random

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc, add_coins, remove_coins
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
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            balance = row[0] or 0 if row else 0
            
            if balance < cost:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Insufficient Funds",
                        f"You need {cost} coins to play slots. You have {balance} coins.",
                        color=discord.Color.red(),
                        footer="Use /daily or /economy balance to earn more",
                        client=interaction.client,
                    )
                )
            
            await remove_coins(interaction.guild.id, interaction.user.id, cost, "GAMBLING", "Slots spin")
            
            symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "7️⃣"]
            reel1, reel2, reel3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
            
            winnings = 0
            if reel1 == reel2 == reel3:
                winnings = 1000 if reel1 == "💎" else 500 if reel1 == "7️⃣" else 300 if reel1 == "⭐" else 200
            elif reel1 == reel2 or reel2 == reel3 or reel1 == reel3:
                winnings = 50
            
            if winnings > 0:
                await add_coins(interaction.guild.id, interaction.user.id, winnings, "GAMBLING", "Slots winnings")
                result_pre = f"**🎉 You won {winnings} coins!**"
                color = discord.Color.gold()
            else:
                result_pre = "**Better luck next time!**"
                color = discord.Color.red()
            
            await db.execute("""
                INSERT INTO gambling_history (guild_id, user_id, game_type, bet_amount, win_amount, result, created_at)
                VALUES (?, ?, 'slots', ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, cost, winnings, "win" if winnings > 0 else "loss", now_utc().isoformat()))
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            nb = (await cur.fetchone())[0] or 0
            await db.commit()
        
        footer = f"Bet: {cost} coins • {'Jackpot! Try again?' if winnings > 0 else 'Play again with /economy gambling slots'}"
        embed = obsidian_embed(
            "🎰 Slots",
            f"**{reel1} | {reel2} | {reel3}**\n\n{result_pre}\n**New Balance:** {nb:,} coins",
            color=color,
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            footer=footer,
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            balance = row[0] or 0 if row else 0
            
            if balance < bet:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Insufficient Funds",
                        f"You need {bet} coins to play. You have {balance} coins.",
                        color=discord.Color.red(),
                        footer="Use /daily or /economy balance to earn more",
                        client=interaction.client,
                    )
                )
            
            await remove_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", "Dice roll")
            user_roll = random.randint(1, 6)
            bot_roll = random.randint(1, 6)
        
        if user_roll > bot_roll:
            winnings = bet * 2
            await add_coins(interaction.guild.id, interaction.user.id, winnings, "GAMBLING", "Dice winnings")
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
            await add_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", "Dice tie (bet returned)")
            result = f"**It's a tie!**\n**Your roll:** {user_roll}\n**Bot roll:** {bot_roll}\n**Bet returned:** {bet} coins"
            color = discord.Color.orange()
            win_amount = bet
            game_result = "tie"
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO gambling_history (guild_id, user_id, game_type, bet_amount, win_amount, result, created_at)
                VALUES (?, ?, 'dice', ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, bet, win_amount, game_result, now_utc().isoformat()))
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            new_balance = (await cur.fetchone())[0] or 0
            await db.commit()
        
        footer = f"Bet: {bet} coins • {'Roll again?' if user_roll > bot_roll else 'Try again with /economy gambling dice'}"
        embed = obsidian_embed(
            "🎲 Dice",
            f"{result}\n**New Balance:** {new_balance:,} coins",
            color=color,
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            footer=footer,
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            balance = row[0] or 0 if row else 0
            
            if balance < bet:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Insufficient Funds",
                        f"You need {bet} coins to play. You have {balance} coins.",
                        color=discord.Color.red(),
                        footer="Use /daily or /economy balance to earn more",
                        client=interaction.client,
                    )
                )
            
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
            await add_coins(interaction.guild.id, interaction.user.id, winnings, "GAMBLING", "Roulette winnings")
            result = f"**🎉 You won!**\n**Landed on:** {landed_color.capitalize()} ({number})\n**Winnings:** {winnings} coins"
            color_emoji = discord.Color.green()
            win_amount = winnings
            game_result = "win"
        else:
            result = f"**You lost!**\n**Landed on:** {landed_color.capitalize()} ({number})\n**Lost:** {bet} coins"
            color_emoji = discord.Color.red()
            win_amount = 0
            game_result = "loss"
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO gambling_history (guild_id, user_id, game_type, bet_amount, win_amount, result, created_at)
                VALUES (?, ?, 'roulette', ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, bet, win_amount, game_result, now_utc().isoformat()))
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            new_balance = (await cur.fetchone())[0] or 0
            await db.commit()
        
        footer = f"Bet: {bet} coins • Landed on {landed_color.capitalize()} • {'Spin again?' if color == landed_color else 'Try red, black, or green'}"
        embed = obsidian_embed(
            "🎰 Roulette",
            f"{result}\n**New Balance:** {new_balance:,} coins",
            color=color_emoji,
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            footer=footer,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
