"""Daily reward command."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, COINS_DAILY_REWARD, format_number, pluralize, EMBED_COLORS


# Streak multiplier thresholds: (min_streak, multiplier, label)
_STREAK_TIERS = [
    (30, 2.0,  "🏆 30-day Legend bonus"),
    (14, 1.5,  "💎 14-day Diamond bonus"),
    (7,  1.25, "🔥 7-day Fire bonus"),
    (1,  1.0,  None),
]


def _streak_multiplier(streak: int) -> tuple[float, str | None]:
    """Return (multiplier, label) for the given streak."""
    for min_s, mult, label in _STREAK_TIERS:
        if streak >= min_s:
            return mult, label
    return 1.0, None


def _streak_emblem(streak: int) -> str:
    """Tiered streak emblem: caps the fire icons at 7 and adds a tier badge past 6.

    Replaces the older "🔥 × min(streak, 10) + ' +N'" pattern. The numeric
    streak is still displayed alongside, so users see the exact count.
    """
    if streak <= 0:
        return ""
    if streak <= 6:
        return "🔥" * streak
    if streak < 14:
        return "🔥" * 7 + " 🌟"
    if streak < 30:
        return "🔥" * 7 + " 💎"
    if streak < 100:
        return "🔥" * 7 + " 🏆"
    return "🔥" * 7 + " 💯"


def _streak_calendar(streak: int) -> str:
    """
    Build a compact 7-day calendar ending today.
    Returns something like: ``M  T  W  T  F  S  S``
                             ``✅ ✅ ✅ ✅ ✅ ⬜ ⬜``
    Days within the current streak are ✅, others ⬜.
    """
    today = datetime.now(timezone.utc).date()
    day_initials = ["M", "T", "W", "T", "F", "S", "S"]
    header = "  ".join(day_initials[(today - timedelta(days=6 - i)).weekday()] for i in range(7))
    cells = []
    for i in range(7):
        delta = 6 - i          # 6 days ago → today
        cells.append("✅" if delta < streak else "⬜")
    return f"`{header}`\n" + "  ".join(cells)


class GracePeriodView(discord.ui.View):
    """Buttons shown when the user missed exactly 1 day and can pay to restore their streak."""

    def __init__(self, streak: int, grace_cost: int):
        super().__init__(timeout=120)
        self.streak = streak
        self.grace_cost = grace_cost

    @discord.ui.button(label="Restore Streak", style=discord.ButtonStyle.success, emoji="🔥")
    async def restore(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Pay the grace fee and keep the streak."""
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        from bot import add_coins, DB_PATH
        import aiosqlite
        from database import remove_coins, get_user_balance

        bal = await get_user_balance(interaction.guild.id, interaction.user.id)
        if bal < self.grace_cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Coins",
                    f"You need **{self.grace_cost:,}** coins to restore your streak but only have **{bal:,}**.",
                    category="error", client=interaction.client,
                ), ephemeral=True,
            )

        today = datetime.now(timezone.utc).date().isoformat()
        new_streak = self.streak + 1
        streak_mult, streak_label = _streak_multiplier(new_streak)
        coins_awarded = int(COINS_DAILY_REWARD * streak_mult)

        ok = await remove_coins(interaction.guild.id, interaction.user.id, self.grace_cost, "GRACE_FEE", "Streak grace period fee")
        if not ok:
            return await interaction.followup.send("Transaction failed. Please try again.", ephemeral=True)

        await add_coins(interaction.guild.id, interaction.user.id, coins_awarded, "DAILY", f"Daily reward (streak: {new_streak}, grace restored)")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE daily_claims SET last_claim_date=?, streak_days=? WHERE guild_id=? AND user_id=?
            """, (today, new_streak, interaction.guild.id, interaction.user.id))
            await db.commit()

        calendar = _streak_calendar(new_streak)
        streak_mult_val, _ = _streak_multiplier(new_streak)
        bonus_coins = int(COINS_DAILY_REWARD * streak_mult_val) - COINS_DAILY_REWARD
        reward_text = f"**{coins_awarded:,}** coins" + (f" _(+{bonus_coins:,} streak bonus)_" if bonus_coins else "")

        await interaction.followup.send(
            embed=obsidian_embed(
                "🔥 Streak Restored!",
                f"> **{new_streak}-day streak** preserved!\n\n"
                f"{calendar}",
                category="prestige",
                fields=[("💰 Daily Reward", reward_text, True)],
                thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                footer="Streak restored! Don't miss tomorrow.",
                client=interaction.client,
            ), ephemeral=True,
        )

    @discord.ui.button(label="Start Fresh (free)", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def fresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Reset streak and claim normally."""
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        # Run normal daily with streak reset
        await _run_daily(interaction, force_reset=True)


def setup(bot, group=None):
    """Register the daily command under /economy and as top-level /daily shortcut."""
    async def daily_callback(interaction: discord.Interaction):
        await _run_daily(interaction)

    group.command(name="daily", description="Claim your daily coin reward!")(daily_callback)
    # Top-level /daily shortcut
    shortcut = app_commands.Command(name="daily", description="Claim your daily coin reward! (shortcut for /economy daily)", callback=daily_callback)
    bot.tree.add_command(shortcut)
    
async def _run_daily(interaction: discord.Interaction, force_reset: bool = False):
    """Claim daily coins (once per day)."""
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
                category="error",
                client=interaction.client,
            ),
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    # Import bot-specific functions inside to avoid circular imports
    from bot import add_coins, DB_PATH
    import aiosqlite

    # Get current date in UTC
    today = datetime.now(timezone.utc).date().isoformat()
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    async with aiosqlite.connect(DB_PATH) as db:
        # Check last claim
        cur = await db.execute(
            "SELECT last_claim_date, streak_days, freeze_used_month FROM daily_claims WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        row = await cur.fetchone()

        if row:
            last_claim_date, streak_days = row[0], int(row[1])
            freeze_used_month = row[2] if len(row) > 2 else None

            # Check if already claimed today
            if last_claim_date == today:
                tomorrow_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                next_ts = int(tomorrow_dt.timestamp())
                streak_fire = _streak_emblem(streak_days)
                fields = [
                    ("🔥 Current Streak", f"{streak_fire}\n{streak_days} day(s)", True),
                    ("⏰ Next Claim", f"<t:{next_ts}:R>", True),
                ]
                embed = obsidian_embed(
                    "⏰ Already Claimed",
                    "You've already claimed your daily reward today!",
                    category="warning",
                    fields=fields,
                    thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                    footer="Come back tomorrow for your next reward",
                    client=interaction.client,
                )
                return await interaction.followup.send(embed=embed, ephemeral=True)

            # Check if streak continues (claimed yesterday) or use streak freeze
            yesterday = datetime.now(timezone.utc).date()
            yesterday_str = (yesterday - timedelta(days=1)).isoformat()

            if last_claim_date == yesterday_str:
                new_streak = streak_days + 1
                used_freeze = False
                offer_grace = False
            elif freeze_used_month != current_month:
                new_streak = streak_days
                used_freeze = True
                offer_grace = False
            else:
                # Missed exactly 1 day (2-day gap)? Offer grace period if streak >= 3
                day_before_yesterday = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
                offer_grace = (last_claim_date == day_before_yesterday and streak_days >= 3 and not force_reset)
                new_streak = 1
                used_freeze = False
        else:
            new_streak = 1
            used_freeze = False
            offer_grace = False

        # Offer grace period before awarding if user missed exactly 1 day
        if offer_grace:
            grace_cost = max(100, int(COINS_DAILY_REWARD * 0.20))  # 20% of daily reward
            tomorrow_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            view = GracePeriodView(streak_days, grace_cost)
            embed = obsidian_embed(
                "😬 You Missed a Day!",
                f"> Your **{streak_days}-day streak** is at risk!\n\n"
                f"Pay **{grace_cost:,} coins** to restore it, or start fresh from day 1.",
                category="warning",
                fields=[
                    ("🔥 Current Streak", f"{streak_days} days", True),
                    ("💸 Restore Cost", f"{grace_cost:,} coins", True),
                    ("⏰ Next Claim", f"<t:{int(tomorrow_dt.timestamp())}:R>", True),
                ],
                thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                footer="You have 2 minutes to decide · Start Fresh is always free",
                client=interaction.client,
            )
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.message = msg
            return

        # Award coins with streak multiplier
        streak_mult, streak_label = _streak_multiplier(new_streak)
        coins_awarded = int(COINS_DAILY_REWARD * streak_mult)
        await add_coins(
            interaction.guild.id,
            interaction.user.id,
            coins_awarded,
            "DAILY",
            f"Daily reward (streak: {new_streak}, {streak_mult}x)",
        )

        # Update or insert claim record (set freeze_used_month when freeze is used)
        freeze_val = current_month if used_freeze else None
        await db.execute("""
            INSERT INTO daily_claims (guild_id, user_id, last_claim_date, streak_days, freeze_used_month)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                last_claim_date = excluded.last_claim_date,
                streak_days = excluded.streak_days,
                freeze_used_month = COALESCE(excluded.freeze_used_month, freeze_used_month)
        """, (
            interaction.guild.id,
            interaction.user.id,
            today,
            new_streak,
            freeze_val,
        ))
        await db.commit()
        if new_streak >= 10:
            try:
                from database import check_and_unlock_achievement
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "daily_streak_10", None, interaction=interaction)
            except Exception:
                pass
        try:
            from database import check_and_unlock_achievement, get_user_balance
            bal = await get_user_balance(interaction.guild.id, interaction.user.id)
            if bal >= 1_000_000:
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "first_million", None, interaction=interaction)
        except Exception:
            pass
        try:
            from database import check_and_unlock_achievement
            if isinstance(interaction.user, discord.Member) and interaction.user.joined_at:
                days_in = (datetime.now(timezone.utc) - interaction.user.joined_at.replace(tzinfo=timezone.utc)).days
                for months, ach_id in [(3, "months_3"), (6, "months_6")]:
                    if days_in >= months * 30:
                        await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, ach_id, None, interaction=interaction)
        except Exception:
            pass

    # Success message with streak calendar and next claim time
    streak_mult, streak_label = _streak_multiplier(new_streak)
    coins_awarded = int(COINS_DAILY_REWARD * streak_mult)
    streak_fire = _streak_emblem(new_streak)
    tomorrow = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    next_ts = int(tomorrow.timestamp())
    next_line = f"<t:{next_ts}:R>"

    # Reward field: base + bonus breakdown
    reward_text = f"**{format_number(coins_awarded)}** {pluralize(coins_awarded, 'coin')}"
    if streak_mult > 1.0:
        base_str = format_number(COINS_DAILY_REWARD)
        bonus_str = format_number(coins_awarded - COINS_DAILY_REWARD)
        reward_text += f"\n_{base_str} base + {bonus_str} streak bonus ({streak_label})_"

    calendar = _streak_calendar(new_streak)
    streak_text = f"{streak_fire}\n**{new_streak}** {pluralize(new_streak, 'day')}\n{calendar}"

    fields = [
        ("💰 Reward", reward_text, True),
        ("🔥 Streak", streak_text, True),
        ("⏰ Next Claim", next_line, True),
    ]
    if used_freeze:
        fields.append(("🛡️ Streak Freeze", "Used 1 monthly freeze to preserve streak", True))

    if new_streak >= 100:
        title, cat = "💯 Century Streak!", "prestige"
    elif new_streak >= 30:
        title, cat = "🌟 30-Day Streak!", "prestige"
    elif new_streak >= 10:
        title, cat = "🔥 10-Day Streak!", "warning"
    else:
        title, cat = "🎁 Daily Reward Claimed!", "economy"

    freeze_note = "\n-# Used your monthly streak freeze." if used_freeze else ""
    from core.command_mentions import command_mention
    bounties_cta = command_mention("economy bounties", fallback="`/economy bounties`")
    desc = (
        f"> **+{format_number(coins_awarded)}** {pluralize(coins_awarded, 'coin')} claimed!\n\n"
        f"Come back after reset for the next one!{freeze_note}\n"
        f"-# 💡 Claim today's bounties too: {bounties_cta}"
    )
    thumb = interaction.user.display_avatar.url if interaction.user.display_avatar else None
    if cat in ("economy", "prestige"):
        embed = embed_template(
            "showcase",
            title,
            desc,
            category=cat,
            fields=fields,
            thumbnail=thumb,
            footer=footer_for("economy_daily"),
            client=interaction.client,
        )
    else:
        embed = obsidian_embed(
            title,
            desc,
            category=cat,
            fields=fields,
            thumbnail=thumb,
            footer=footer_for("economy_daily"),
            client=interaction.client,
        )
    from core.help_layout import help_layout_v2_enabled
    from core.daily_layout import DailyLayout

    if help_layout_v2_enabled():
        try:
            layout = DailyLayout(title=title, description=desc, fields=fields)
            await interaction.followup.send(view=layout, ephemeral=True)
            return
        except Exception:
            pass
    await interaction.followup.send(embed=embed, ephemeral=True)
