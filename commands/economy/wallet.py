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
from core.refresh_panels import refresh_edit_message, register_refresh_panel
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


async def refresh_wallet_panel(interaction: discord.Interaction, payload: dict) -> bool:
    """Persistent refresh handler for wallet panels."""
    from core.utils import BUTTON_ONLY_RUNNER_MSG
    from core.refresh_panels import runner_only

    if not await runner_only(interaction, payload, BUTTON_ONLY_RUNNER_MSG):
        return False
    if not interaction.guild:
        return False

    class _WalletInter:
        def __init__(self, inter: discord.Interaction):
            self.guild = inter.guild
            self.user = inter.user
            self.client = inter.client

    fake = _WalletInter(interaction)
    from core.wallet_layout import wallet_layout_v2_enabled, WalletLayout

    if wallet_layout_v2_enabled():
        try:
            emb = await _build_wallet_embed(fake)  # type: ignore[arg-type]
            fields = [(f.name, f.value, f.inline) for f in emb.fields]
            layout = WalletLayout(
                title=emb.title or "💼 Your Wallet",
                intro=emb.description or "",
                fields=fields,
                on_refresh=lambda i: refresh_wallet_panel(i, payload),
            )
            await refresh_edit_message(interaction, view=layout, panel_type="eco_wallet", payload=payload)
            return True
        except Exception:
            pass
    new_embed = await _build_wallet_embed(fake)  # type: ignore[arg-type]
    view = RefreshView.panel("eco_wallet", payload=payload)
    await refresh_edit_message(
        interaction, embed=new_embed, view=view, panel_type="eco_wallet", payload=payload,
    )
    return True


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
        payload = {
            "runner_id": interaction.user.id,
            "guild_id": interaction.guild.id,
        }

        from core.wallet_layout import wallet_layout_v2_enabled, WalletLayout

        if wallet_layout_v2_enabled():
            try:
                fields = [(f.name, f.value, f.inline) for f in embed.fields]
                layout = WalletLayout(
                    title=embed.title or "💼 Your Wallet",
                    intro=embed.description or "",
                    fields=fields,
                    on_refresh=lambda i: refresh_wallet_panel(i, payload),
                )
                await interaction.response.send_message(view=layout, ephemeral=True)
                msg = await interaction.original_response()
                await register_refresh_panel(msg, "eco_wallet", payload)
                return
            except Exception:
                pass

        view = RefreshView.panel("eco_wallet", payload=payload)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        msg = await interaction.original_response()
        await register_refresh_panel(msg, "eco_wallet", payload)
