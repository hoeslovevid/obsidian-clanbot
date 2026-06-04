"""Compact personal dashboard (Item 11).

Tight ephemeral summary that reuses :func:`commands.general.profile.get_user_profile_data`
so we avoid duplicating queries. Layout: 3-4 inline fields, no big "Recent
Achievements" section. Footer surfaces the most urgent next-action.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
import aiosqlite

from core.utils import (
    obsidian_embed,
    error_embed,
    feature_off_embed,
    ECONOMY_ENABLED,
    EMBED_COLORS,
    format_number,
    pluralize,
    render_bar,
    discord_timestamp,
)
from database import DB_PATH


def _next_daily_ts(today_claimed: bool) -> Optional[int]:
    if not today_claimed:
        return None
    tomorrow = (
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )
    return int(tomorrow.timestamp())


async def _run_me(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            embed=error_embed(
                "Invalid Context",
                "This command can only be used in a server.",
                client=interaction.client,
            ),
            ephemeral=True,
        )
    if not ECONOMY_ENABLED:
        return await interaction.response.send_message(
            embed=feature_off_embed("Economy", client=interaction.client),
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)

    # Reuse the heavy data loader from profile.py — single source of truth.
    from commands.general.profile import get_user_profile_data
    data = await get_user_profile_data(interaction.guild.id, interaction.user.id)

    # XP progress (mirrors profile.py math but in tighter form).
    from database import xp_for_level, xp_for_next_level
    from core.utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT

    cur_level = data["level"] or 0
    cur_xp = data["xp"] or 0
    xp_cur = xp_for_level(cur_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT) if cur_level > 0 else 0
    xp_next = xp_for_next_level(cur_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
    rng = max(1, xp_next - xp_cur)
    pct = min(100, int(100 * (cur_xp - xp_cur) / rng))

    # Streak emblem (reuses Item 25 helper)
    from commands.economy.daily import _streak_emblem
    streak = data.get("daily_streak") or 0

    # Daily claim status: today already?
    today_iso = datetime.now(timezone.utc).date().isoformat()
    today_claimed = False
    inv_row = None
    reminders_count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        row = await cur.fetchone()
        if row and row[0] == today_iso:
            today_claimed = True
        cur = await db.execute(
            "SELECT amount, interest_rate, maturity_date, collected FROM investments "
            "WHERE guild_id=? AND user_id=? AND collected=0 "
            "ORDER BY invested_at DESC LIMIT 1",
            (interaction.guild.id, interaction.user.id),
        )
        inv_row = await cur.fetchone()
        try:
            cur = await db.execute(
                "SELECT COUNT(*) FROM reminders WHERE guild_id=? AND user_id=? AND sent=0",
                (interaction.guild.id, interaction.user.id),
            )
            r = await cur.fetchone()
            if r:
                reminders_count = int(r[0] or 0)
        except Exception:
            reminders_count = 0

    next_daily = _next_daily_ts(today_claimed)
    next_daily_text = (
        f"<t:{next_daily}:R>" if next_daily else "✅ Ready! Run `/daily`."
    )

    # --- Field 1: Coins / XP ---
    coin_field = (
        f"**{format_number(data['balance'])}** {pluralize(data['balance'], 'coin')}\n"
        f"-# Total earned: {format_number(data['total_earned'])}"
    )

    xp_field = (
        f"**Level {cur_level}**\n"
        f"{format_number(cur_xp)} / {format_number(xp_next)}\n"
        f"{render_bar(pct)}"
    )

    # --- Field 2: Streak / Next daily ---
    streak_field = (
        f"{_streak_emblem(streak) or '—'}\n"
        f"**{streak}** {pluralize(streak, 'day')}\n"
        f"Next: {next_daily_text}"
    )

    # --- Field 3: Investment ---
    investment_field = "_No active investment_\n-# Try `/economy invest`"
    investment_urgent = False
    if inv_row:
        inv_amt, inv_rate, inv_maturity_str, _col = inv_row
        payout = int(inv_amt * (1 + (inv_rate or 0)))
        try:
            inv_mat = datetime.fromisoformat(str(inv_maturity_str).replace("Z", "+00:00"))
            mat_ts = int(inv_mat.timestamp())
            ready = datetime.now(timezone.utc) >= inv_mat
        except Exception:
            mat_ts = 0
            ready = False
        if ready:
            investment_urgent = True
            investment_field = (
                f"**{format_number(payout)}** payout\n"
                f"✅ Ready — `/economy invest_collect`"
            )
        else:
            investment_field = (
                f"**{format_number(payout)}** at maturity\n"
                f"Matures <t:{mat_ts}:R>"
            )

    fields = [
        ("💰 Coins", coin_field, True),
        ("⭐ XP", xp_field, True),
        ("🔥 Streak", streak_field, True),
        ("📈 Investment", investment_field, True),
    ]

    # --- Field 4: Pet (if owned) ---
    pet_urgent = False
    if data.get("pet"):
        from commands.economy.pets import (
            _apply_decay,
            HUNGER_DECAY_PER_HOUR,
            HAPPINESS_DECAY_PER_HOUR,
            get_pet_emoji,
        )
        pet = data["pet"]
        h = _apply_decay(pet.get("hunger") or 100, pet.get("last_fed"), pet.get("created_at"), HUNGER_DECAY_PER_HOUR)
        hp = _apply_decay(pet.get("happiness") or 100, pet.get("last_played"), pet.get("created_at"), HAPPINESS_DECAY_PER_HOUR)
        h_icon = "🚨" if h < 25 else "⚠️" if h < 50 else "✅"
        hp_icon = "🚨" if hp < 25 else "⚠️" if hp < 50 else "😊"
        pet_urgent = (h < 50 or hp < 50)
        fields.append((
            f"{get_pet_emoji(pet.get('type'))} {pet.get('name') or pet.get('type') or 'Pet'}",
            f"Hunger: {h}/100 {h_icon}\n"
            f"Happy: {hp}/100 {hp_icon}",
            True,
        ))

    if reminders_count:
        fields.append((
            "🔔 Reminders",
            f"**{reminders_count}** pending\n-# `/general reminder list`",
            True,
        ))

    # Footer: pick the most urgent helpful hint
    if pet_urgent:
        footer = "🐾 Pet needs attention — `/pets feed` / `play`"
    elif investment_urgent:
        footer = "📈 Investment ready! Use `/economy invest_collect`"
    elif not today_claimed:
        footer = "🎁 Daily not claimed — run `/daily`"
    elif reminders_count:
        footer = f"🔔 {reminders_count} reminder(s) waiting"
    elif next_daily:
        footer = f"Next daily in <t:{next_daily}:R>"
    else:
        footer = "Use /help to explore commands"

    embed = obsidian_embed(
        f"👋 {interaction.user.display_name}",
        f"A quick snapshot of your account in **{interaction.guild.name}**.",
        color=EMBED_COLORS["general"],
        template="profile",
        profile_category="general",
        author=interaction.user if isinstance(interaction.user, discord.Member) else None,
        thumbnail=(
            interaction.user.display_avatar.url
            if hasattr(interaction.user, "display_avatar")
            else None
        ),
        fields=fields,
        footer=footer,
        client=interaction.client,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot, group=None):
    """Register `/me` as a top-level shortcut.

    We deliberately skip the group registration: ``/general`` already sits
    near Discord's 25-command limit, and ``/me`` is most discoverable as a
    top-level shortcut anyway.
    """
    async def me_callback(interaction: discord.Interaction):
        await _run_me(interaction)

    shortcut = app_commands.Command(
        name="me",
        description="Quick personal snapshot: coins, XP, streak, pet.",
        callback=me_callback,
    )
    bot.tree.add_command(shortcut)
