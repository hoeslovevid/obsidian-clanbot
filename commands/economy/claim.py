"""/claim — unified hub for daily reward, bounties, and investment status."""
from __future__ import annotations

import discord
from datetime import datetime, timezone, timedelta

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, EMBED_COLORS, format_number
from core.db import open_db
from database import now_utc


def setup(bot, group=None):
    """Top-level /claim shortcut (economy group is near capacity)."""
    group = None

    @bot.tree.command(
        name="claim",
        description="See what's ready to claim — daily, bounties, and investments.",
    )
    async def claim(interaction: discord.Interaction):
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        from core.command_mentions import command_mention
        from core.user_prefs import compact_embeds

        gid = interaction.guild.id
        uid = interaction.user.id
        compact = await compact_embeds(gid, uid)
        lines: list[str] = []

        today = datetime.now(timezone.utc).date().isoformat()
        async with open_db() as db:
            cur = await db.execute(
                "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
                (gid, uid),
            )
            row = await cur.fetchone()
        daily_ready = not row or row[0] != today
        if daily_ready:
            lines.append(f"🎁 **Daily** — ✅ ready · {command_mention('daily', fallback='`/daily`')}")
        else:
            tomorrow = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            lines.append(f"🎁 **Daily** — claimed · next <t:{int(tomorrow.timestamp())}:R>")

        try:
            from commands.economy.bounties import get_claimable_bounties

            claimable = await get_claimable_bounties(gid, uid)
            if claimable:
                total = sum(b["reward"] for b in claimable)
                lines.append(
                    f"🎯 **Bounties** — {len(claimable)} ready ({format_number(total)} coins) · "
                    f"{command_mention('economy bounties', fallback='`/economy bounties`')}"
                )
            else:
                midnight = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + timedelta(days=1)
                lines.append(f"🎯 **Bounties** — none ready · reset <t:{int(midnight.timestamp())}:R>")
        except Exception:
            lines.append("🎯 **Bounties** — unavailable")

        async with open_db() as db:
            cur = await db.execute(
                "SELECT maturity_date FROM investments WHERE guild_id=? AND user_id=? AND collected=0 "
                "ORDER BY maturity_date ASC LIMIT 1",
                (gid, uid),
            )
            row = await cur.fetchone()
        if row and row[0]:
            try:
                mat = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                if mat.tzinfo is None:
                    mat = mat.replace(tzinfo=timezone.utc)
                if mat <= now_utc():
                    lines.append(
                        f"📈 **Investment** — ✅ matured · "
                        f"{command_mention('economy invest_status', fallback='`/economy invest_status`')}"
                    )
                else:
                    lines.append(f"📈 **Investment** — matures <t:{int(mat.timestamp())}:R>")
            except Exception:
                pass

        embed = obsidian_embed(
            "💰 Claim Hub",
            "\n".join(lines) or "Nothing to claim right now.",
            color=EMBED_COLORS.get("economy", discord.Color.gold()),
            footer="Daily auto-claims bounties when you run `/daily`",
            client=interaction.client,
            compact=compact,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
