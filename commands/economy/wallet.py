"""Unified wallet — coins, XP, streak, and daily timer in one embed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord  # type: ignore
from discord import app_commands  # type: ignore

from commands.general.profile import get_user_profile_data
from core.embed_templates import embed_template
from core.utils import (
    ECONOMY_ENABLED,
    XP_ENABLED,
    XP_LEVEL_EXPONENT,
    XP_LEVEL_MULTIPLIER,
    feature_off_embed,
    format_number,
    render_bar,
)
from database import xp_for_level, xp_for_next_level
from views import RefreshView


async def _build_wallet_embed(interaction: discord.Interaction) -> discord.Embed:
    guild = interaction.guild
    user = interaction.user
    assert guild is not None

    data = await get_user_profile_data(guild.id, user.id)
    balance = int(data.get("balance") or 0)
    total_earned = int(data.get("total_earned") or 0)
    streak = int(data.get("daily_streak") or 0)
    level = int(data.get("level") or 0)
    xp = int(data.get("xp") or 0)
    total_xp = int(data.get("total_xp") or 0)

    bar_max = 100_000
    coin_pct = min(100, int(100 * balance / bar_max)) if bar_max else 0

    fields: list[tuple[str, str, bool]] = [
        (
            "💰 Coins",
            f"**{format_number(balance)}** coins\n{render_bar(coin_pct)}\n-# Total earned: {format_number(total_earned)}",
            True,
        ),
    ]

    if XP_ENABLED:
        xp_for_current = xp_for_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT) if level > 0 else 0
        xp_for_next = xp_for_next_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
        xp_progress = xp - xp_for_current
        xp_range = xp_for_next - xp_for_current
        progress_percent = int((xp_progress / xp_range * 100)) if xp_range > 0 else 100
        fields.append(
            (
                f"⭐ Level {level}",
                f"{format_number(xp)} / {format_number(xp_for_next)} XP\n{render_bar(progress_percent)}\n-# Total: {format_number(total_xp)} XP",
                True,
            )
        )

    streak_line = f"**{streak}** day{'s' if streak != 1 else ''}"
    if streak > 0:
        from commands.economy.daily import _streak_emblem

        emblem = _streak_emblem(streak)
        if emblem:
            streak_line = f"{emblem} {streak_line}"
    fields.append(("🔥 Daily streak", streak_line, True))

    next_daily = "Available now — use **`/daily`**"
    if ECONOMY_ENABLED:
        from database import DB_PATH
        import aiosqlite

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
                (guild.id, user.id),
            )
            daily_row = await cur.fetchone()
        if daily_row and daily_row[0]:
            today = datetime.now(timezone.utc).date().isoformat()
            if daily_row[0] == today:
                next_dt = (
                    datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                    + timedelta(days=1)
                )
                next_daily = f"Next claim <t:{int(next_dt.timestamp())}:R>"

    fields.append(("🎁 Daily reward", next_daily, False))

    return embed_template(
        "showcase",
        "💼 Your Wallet",
        f"> {user.mention} — coins, XP, and daily progress at a glance.",
        category="economy",
        author_name=user.display_name,
        author_icon=user.display_avatar.url if user.display_avatar else None,
        thumbnail=user.display_avatar.url if user.display_avatar else None,
        fields=fields,
        footer="Tap **Refresh** to update • /economy transactions for history",
        client=interaction.client,
        brand=True,
    )


def setup(bot, group=None):
    """Register /economy wallet."""

    @group.command(name="wallet", description="Coins, XP, streak, and daily timer in one place.")
    async def wallet(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=embed_template(
                    "error",
                    "Server only",
                    "Use this inside a server.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        if not ECONOMY_ENABLED and not XP_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable economy or XP.", client=interaction.client),
                ephemeral=True,
            )

        embed = await _build_wallet_embed(interaction)

        async def refresh_cb(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                from core.utils import BUTTON_ONLY_RUNNER_MSG

                return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            await btn_interaction.response.defer(ephemeral=True)
            new_embed = await _build_wallet_embed(btn_interaction)
            view = RefreshView(refresh_cb)
            await btn_interaction.message.edit(embed=new_embed, view=view)

        view = RefreshView(refresh_cb)
        from core.wallet_layout import WalletSnapshotLayout, wallet_layout_v2_enabled

        if wallet_layout_v2_enabled():
            data = await get_user_profile_data(interaction.guild.id, interaction.user.id)
            body = (
                f"**{format_number(int(data.get('balance') or 0))}** coins · "
                f"Lv **{int(data.get('level') or 0)}** · streak **{int(data.get('daily_streak') or 0)}**d"
            )
            layout = WalletSnapshotLayout(title="💼 Wallet snapshot", body=body)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            await interaction.followup.send(view=layout, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
