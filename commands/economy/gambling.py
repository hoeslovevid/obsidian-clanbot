"""Gambling games commands."""
import discord
from discord import app_commands
from typing import Optional, Dict, Tuple
import random

from core.utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc, add_coins, remove_coins
import aiosqlite


MIN_SLOTS_BET, MAX_SLOTS_BET = 10, 5_000
_DEFAULT_BET = 50

# In-memory last-bet store: (guild_id, user_id, game) -> bet amount
_last_bets: Dict[Tuple[int, int, str], int] = {}


def _remember_bet(guild_id: int, user_id: int, game: str, bet: int) -> None:
    _last_bets[(guild_id, user_id, game)] = bet


def _recall_bet(guild_id: int, user_id: int, game: str, default: int) -> int:
    return _last_bets.get((guild_id, user_id, game), default)


async def _play_slots(
    interaction: discord.Interaction,
    bet: int,
    *,
    edit_original: bool = False,
) -> None:
    """Core slots logic. Assumes the interaction is already deferred."""
    if not interaction.guild:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        row = await cur.fetchone()
        balance = row[0] or 0 if row else 0

        if balance < bet:
            err_embed = obsidian_embed(
                "❌ Insufficient Funds",
                f"You need **{bet:,}** coins to spin at that bet. You have **{balance:,}** coins.\n\nUse `/daily` or send messages to earn more!",
                color=discord.Color.red(),
                footer="Use /daily or /economy balance to earn more",
                client=interaction.client,
            )
            if edit_original:
                await interaction.edit_original_response(embed=err_embed, view=None)
            else:
                await interaction.followup.send(embed=err_embed)
            return

        low_balance_warning = (balance - bet) < 100
        _remember_bet(interaction.guild.id, interaction.user.id, "slots", bet)
        await remove_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", f"Slots spin (bet {bet})")

        symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "7️⃣"]
        reel1, reel2, reel3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)

        winnings = 0
        if reel1 == reel2 == reel3:
            mult = 20 if reel1 == "💎" else 10 if reel1 == "7️⃣" else 6 if reel1 == "⭐" else 4
            winnings = bet * mult
        elif reel1 == reel2 or reel2 == reel3 or reel1 == reel3:
            winnings = bet * 2

        if winnings > 0:
            await add_coins(interaction.guild.id, interaction.user.id, winnings, "GAMBLING", f"Slots winnings (bet {bet})")
            try:
                from database import check_and_unlock_achievement, get_user_balance
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "gambling_first_win", None, interaction=interaction)
                if winnings >= 1000:
                    await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "gambling_jackpot", None, interaction=interaction)
                nb_check = await get_user_balance(interaction.guild.id, interaction.user.id)
                if nb_check >= 1_000_000:
                    await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "first_million", None, interaction=interaction)
            except Exception:
                pass
            profit = winnings - bet
            result_pre = f"**🎉 You won {winnings:,} coins!** (profit: +{profit:,})"
            color = discord.Color.gold()
        else:
            result_pre = f"**Better luck next time!** (lost {bet:,} coins)"
            color = discord.Color.red()

        await db.execute("""
            INSERT INTO gambling_history (guild_id, user_id, game_type, bet_amount, win_amount, result, created_at)
            VALUES (?, ?, 'slots', ?, ?, ?, ?)
        """, (interaction.guild.id, interaction.user.id, bet, winnings, "win" if winnings > 0 else "loss", now_utc().isoformat()))
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        nb = (await cur.fetchone())[0] or 0
        await db.commit()

    low_warn = "\n\n⚠️ **Low balance!** Consider saving for your daily." if low_balance_warning and nb < 100 else ""
    footer = f"Bet: {bet:,} coins • {'Jackpot! Try again!' if winnings > 0 else 'Try your luck again!'}"
    embed = obsidian_embed(
        "🎰 Slots",
        f"**{reel1} | {reel2} | {reel3}**\n\n{result_pre}\n**New Balance:** {nb:,} coins{low_warn}",
        color=color,
        thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
        footer=footer,
        client=interaction.client,
    )
    view = PlayAgainSlotsView(bet)
    if edit_original:
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.followup.send(embed=embed, view=view)


async def _play_dice(
    interaction: discord.Interaction,
    bet: int,
    *,
    edit_original: bool = False,
) -> None:
    """Core dice logic. Assumes the interaction is already deferred."""
    if not interaction.guild:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        row = await cur.fetchone()
        balance = row[0] or 0 if row else 0

        if balance < bet:
            err_embed = obsidian_embed(
                "❌ Insufficient Funds",
                f"You need {bet:,} coins to play dice. You have **{balance:,}** coins.\n\nUse `/daily` or send messages to earn more!",
                color=discord.Color.red(),
                footer="Use /daily or /economy balance to earn more",
                client=interaction.client,
            )
            if edit_original:
                await interaction.edit_original_response(embed=err_embed, view=None)
            else:
                await interaction.followup.send(embed=err_embed)
            return

        low_balance_warning = (balance - bet) < 100
        _remember_bet(interaction.guild.id, interaction.user.id, "dice", bet)
        await remove_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", "Dice roll")
        user_roll = random.randint(1, 6)
        bot_roll = random.randint(1, 6)

    if user_roll > bot_roll:
        winnings = bet * 2
        await add_coins(interaction.guild.id, interaction.user.id, winnings, "GAMBLING", "Dice winnings")
        try:
            from database import check_and_unlock_achievement
            await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "gambling_first_win", None, interaction=interaction)
        except Exception:
            pass
        result = f"**🎉 You won!**\n**Your roll:** {user_roll}\n**Bot roll:** {bot_roll}\n**Winnings:** {winnings:,} coins"
        color = discord.Color.green()
        win_amount = winnings
        game_result = "win"
    elif user_roll < bot_roll:
        result = f"**You lost!**\n**Your roll:** {user_roll}\n**Bot roll:** {bot_roll}\n**Lost:** {bet:,} coins"
        color = discord.Color.red()
        win_amount = 0
        game_result = "loss"
    else:
        await add_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", "Dice tie (bet returned)")
        result = f"**It's a tie!**\n**Your roll:** {user_roll}\n**Bot roll:** {bot_roll}\n**Bet returned:** {bet:,} coins"
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

    low_warn = "\n\n⚠️ **Low balance!** Consider saving for your daily." if low_balance_warning and new_balance < 100 else ""
    footer = f"Bet: {bet:,} coins • {'Roll again!' if user_roll > bot_roll else 'Try again!'}"
    embed = obsidian_embed(
        "🎲 Dice",
        f"{result}\n**New Balance:** {new_balance:,} coins{low_warn}",
        color=color,
        thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
        footer=footer,
        client=interaction.client,
    )
    view = PlayAgainDiceView(bet)
    if edit_original:
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.followup.send(embed=embed, view=view)


async def _play_roulette(
    interaction: discord.Interaction,
    bet: int,
    chosen_color: str,
    *,
    edit_original: bool = False,
) -> None:
    """Core roulette logic. Assumes the interaction is already deferred."""
    if not interaction.guild:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        row = await cur.fetchone()
        balance = row[0] or 0 if row else 0

        if balance < bet:
            err_embed = obsidian_embed(
                "❌ Insufficient Funds",
                f"You need {bet:,} coins to play roulette. You have **{balance:,}** coins.\n\nUse `/daily` or send messages to earn more!",
                color=discord.Color.red(),
                footer="Use /daily or /economy balance to earn more",
                client=interaction.client,
            )
            if edit_original:
                await interaction.edit_original_response(embed=err_embed, view=None)
            else:
                await interaction.followup.send(embed=err_embed)
            return

        low_balance_warning = (balance - bet) < 100
        _remember_bet(interaction.guild.id, interaction.user.id, "roulette", bet)
        await remove_coins(interaction.guild.id, interaction.user.id, bet, "GAMBLING", "Roulette bet")

    number = random.randint(0, 36)
    if number == 0:
        landed_color = "green"
    elif number in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]:
        landed_color = "red"
    else:
        landed_color = "black"

    if chosen_color == landed_color:
        if chosen_color == "green":
            winnings = bet * 35
        else:
            winnings = bet * 2
        await add_coins(interaction.guild.id, interaction.user.id, winnings, "GAMBLING", "Roulette winnings")
        try:
            from database import check_and_unlock_achievement
            await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "gambling_first_win", None, interaction=interaction)
        except Exception:
            pass
        result = f"**🎉 You won!**\n**Landed on:** {landed_color.capitalize()} ({number})\n**Winnings:** {winnings:,} coins"
        color_embed = discord.Color.green()
        win_amount = winnings
        game_result = "win"
    else:
        result = f"**You lost!**\n**Landed on:** {landed_color.capitalize()} ({number})\n**Lost:** {bet:,} coins"
        color_embed = discord.Color.red()
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

    low_warn = "\n\n⚠️ **Low balance!** Consider saving for your daily." if low_balance_warning and new_balance < 100 else ""
    footer = f"Bet: {bet:,} coins • Landed on {landed_color.capitalize()} • {'Spin again!' if chosen_color == landed_color else 'Try red, black, or green'}"
    embed = obsidian_embed(
        "🎰 Roulette",
        f"{result}\n**New Balance:** {new_balance:,} coins{low_warn}",
        color=color_embed,
        thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
        footer=footer,
        client=interaction.client,
    )
    view = PlayAgainRouletteView(bet, chosen_color)
    if edit_original:
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.followup.send(embed=embed, view=view)


class PlayAgainSlotsView(discord.ui.View):
    """Play Again button for slots."""

    def __init__(self, bet: int):
        super().__init__(timeout=60)
        self.bet = bet

    @discord.ui.button(label="🎰 Play Again", style=discord.ButtonStyle.primary)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Only works in servers.", ephemeral=True)
        await interaction.response.defer()
        await _play_slots(interaction, self.bet, edit_original=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


class PlayAgainDiceView(discord.ui.View):
    """Play Again button for dice."""

    def __init__(self, bet: int):
        super().__init__(timeout=60)
        self.bet = bet

    @discord.ui.button(label="🎲 Roll Again", style=discord.ButtonStyle.primary)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Only works in servers.", ephemeral=True)
        await interaction.response.defer()
        await _play_dice(interaction, self.bet, edit_original=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


class PlayAgainRouletteView(discord.ui.View):
    """Play Again button for roulette (same color and bet)."""

    def __init__(self, bet: int, chosen_color: str):
        super().__init__(timeout=60)
        self.bet = bet
        self.chosen_color = chosen_color
        color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}.get(chosen_color, "🎰")
        self.children[0].label = f"{color_emoji} Spin Again ({chosen_color.capitalize()})"  # type: ignore[index]

    @discord.ui.button(label="🎰 Spin Again", style=discord.ButtonStyle.primary)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Only works in servers.", ephemeral=True)
        await interaction.response.defer()
        await _play_roulette(interaction, self.bet, self.chosen_color, edit_original=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


def setup(bot, group=None):
    """Register gambling commands."""

    stats_decorator = group.command(name="gamble_stats", description="View your gambling statistics and win rate.") if group else bot.tree.command(name="gamble_stats", description="View your gambling statistics.")

    @stats_decorator
    @app_commands.describe(user="Member to look up (defaults to yourself)")
    async def gamble_stats(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Show gambling win/loss stats for a user."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This command can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        target = user or interaction.user
        is_self = target.id == interaction.user.id
        await interaction.response.defer(ephemeral=is_self)

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT game_type,
                       COUNT(*) AS plays,
                       COALESCE(SUM(CASE WHEN result='win' THEN 1 ELSE 0 END), 0) AS wins,
                       COALESCE(SUM(bet_amount), 0) AS total_wagered,
                       COALESCE(SUM(win_amount - bet_amount), 0) AS net_profit,
                       MAX(win_amount) AS biggest_win,
                       MAX(bet_amount) AS biggest_bet
                FROM gambling_history
                WHERE guild_id=? AND user_id=?
                GROUP BY game_type
            """, (interaction.guild.id, target.id))
            rows = await cur.fetchall()

            cur = await db.execute("""
                SELECT COUNT(*),
                       COALESCE(SUM(CASE WHEN result='win' THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(bet_amount), 0),
                       COALESCE(SUM(win_amount - bet_amount), 0),
                       MAX(win_amount)
                FROM gambling_history
                WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, target.id))
            totals = await cur.fetchone()

        if not totals or totals[0] == 0:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🎲 No Gambling History",
                    f"{target.mention} hasn't played any games yet.",
                    category="economy",
                    client=interaction.client,
                ),
                ephemeral=is_self,
            )

        total_plays, total_wins, total_wagered, net_profit, biggest_win = totals
        total_losses = total_plays - total_wins
        win_rate = int(100 * total_wins / total_plays) if total_plays > 0 else 0
        profit_sign = "+" if net_profit >= 0 else ""

        fields = []
        game_name_map = {"slots": "🎰 Slots", "dice": "🎲 Dice", "roulette": "🎡 Roulette"}
        for game_type, plays, wins, wagered, net, bwin, bbet in rows:
            losses = plays - wins
            wr = int(100 * wins / plays) if plays > 0 else 0
            p_sign = "+" if net >= 0 else ""
            fields.append((
                game_name_map.get(game_type, game_type.title()),
                f"**Plays:** {plays:,}  ·  **W/L:** {wins}/{losses}\n"
                f"**Win rate:** {wr}%  ·  **Net:** {p_sign}{net:,}\n"
                f"**Wagered:** {wagered:,}  ·  **Best win:** {bwin:,}",
                True,
            ))

        net_sign = "+" if net_profit >= 0 else ""
        embed = obsidian_embed(
            f"🎲 Gambling Stats — {target.display_name}",
            f"> **{total_wins}W / {total_losses}L** across {total_plays:,} games\n"
            f"> Win rate: **{win_rate}%**  ·  Net: **{net_sign}{net_profit:,}** coins",
            category="economy",
            thumbnail=target.display_avatar.url if target.display_avatar else None,
            fields=fields if fields else None,
            footer=f"Total wagered: {total_wagered:,} coins  ·  Best win: {biggest_win:,} coins",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=is_self)

    command_decorator = group.command(name="slots", description="Play slots! Bet 10–5,000 coins.") if group else bot.tree.command(name="slots", description="Play slots! Bet 10–5,000 coins.")

    @command_decorator
    @app_commands.describe(bet="Coins to bet (10–5,000). Defaults to your last bet if omitted.")
    async def slots(interaction: discord.Interaction, bet: Optional[int] = None):
        """Play a slot machine game."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        resolved_bet = bet if bet is not None else _recall_bet(interaction.guild.id, interaction.user.id, "slots", _DEFAULT_BET)
        if not (MIN_SLOTS_BET <= resolved_bet <= MAX_SLOTS_BET):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Bet",
                    f"Bet must be between **{MIN_SLOTS_BET:,}** and **{MAX_SLOTS_BET:,}** coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.defer()
        await _play_slots(interaction, resolved_bet)

    command_decorator = group.command(name="dice", description="Roll dice! Bet coins and try to roll higher than the bot.") if group else bot.tree.command(name="dice", description="Roll dice! Bet coins and try to roll higher than the bot.")

    @command_decorator
    @app_commands.describe(bet="Amount of coins to bet. Defaults to your last bet if omitted.")
    async def dice(interaction: discord.Interaction, bet: Optional[int] = None):
        """Play dice game."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        resolved_bet = bet if bet is not None else _recall_bet(interaction.guild.id, interaction.user.id, "dice", _DEFAULT_BET)
        if resolved_bet < 1:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Bet",
                    "Bet must be at least 1 coin.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.defer()
        await _play_dice(interaction, resolved_bet)

    command_decorator = group.command(name="roulette", description="Play roulette! Bet on red, black, or green.") if group else bot.tree.command(name="roulette", description="Play roulette! Bet on red, black, or green.")

    @command_decorator
    @app_commands.describe(bet="Amount of coins to bet. Defaults to your last bet if omitted.", color="Color to bet on (red/black/green)")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red", value="red"),
        app_commands.Choice(name="Black", value="black"),
        app_commands.Choice(name="Green", value="green"),
    ])
    async def roulette(interaction: discord.Interaction, color: str, bet: Optional[int] = None):
        """Play roulette game."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        resolved_bet = bet if bet is not None else _recall_bet(interaction.guild.id, interaction.user.id, "roulette", _DEFAULT_BET)
        if resolved_bet < 1:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Bet",
                    "Bet must be at least 1 coin.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.defer()
        await _play_roulette(interaction, resolved_bet, color)
