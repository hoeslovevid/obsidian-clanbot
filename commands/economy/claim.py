"""/claim — unified hub for daily reward, bounties, and investment status."""
from __future__ import annotations

import discord
from datetime import datetime, timezone, timedelta

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, EMBED_COLORS, format_number, success_embed
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
        from core.embed_prefs import embed_kwargs

        gid = interaction.guild.id
        uid = interaction.user.id
        ek = await embed_kwargs(gid, uid)
        lines: list[str] = []
        has_actions = False
        bounty_ready = False
        invest_ready = False

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
            has_actions = True
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
                bounty_ready = True
                has_actions = True
                lines.append(
                    f"🎯 **Bounties** — {len(claimable)} ready ({format_number(total)} coins)"
                )
            else:
                midnight = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + timedelta(days=1)
                lines.append(f"🎯 **Bounties** — none ready · reset <t:{int(midnight.timestamp())}:R>")
        except Exception:
            lines.append("🎯 **Bounties** — unavailable")

        try:
            from commands.economy.pets import _apply_decay, HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR

            async with open_db() as db:
                cur = await db.execute(
                    "SELECT hunger, happiness, last_fed, last_played, created_at, name "
                    "FROM pets WHERE guild_id=? AND user_id=?",
                    (gid, uid),
                )
                pet = await cur.fetchone()
            if pet:
                h = _apply_decay(pet[0] or 100, pet[2], pet[4], HUNGER_DECAY_PER_HOUR)
                hp = _apply_decay(pet[1] or 100, pet[3], pet[4], HAPPINESS_DECAY_PER_HOUR)
                if h < 50 or hp < 50:
                    lines.append(f"🐾 **{pet[5] or 'Pet'}** — needs care")
                else:
                    lines.append(f"🐾 **{pet[5] or 'Pet'}** — ✅ doing fine")
        except Exception:
            pass

        invest_id = None
        async with open_db() as db:
            cur = await db.execute(
                "SELECT id, maturity_date FROM investments WHERE guild_id=? AND user_id=? AND collected=0 "
                "ORDER BY maturity_date ASC LIMIT 1",
                (gid, uid),
            )
            row = await cur.fetchone()
        if row:
            invest_id, mat_raw = row[0], row[1]
            try:
                mat = datetime.fromisoformat(str(mat_raw).replace("Z", "+00:00"))
                if mat.tzinfo is None:
                    mat = mat.replace(tzinfo=timezone.utc)
                if mat <= now_utc():
                    invest_ready = True
                    has_actions = True
                    lines.append("📈 **Investment** — ✅ matured and ready to collect")
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
            **ek,
        )

        if has_actions:

            class _ClaimHubView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=120)
                    if bounty_ready:
                        btn = discord.ui.Button(
                            label="Claim bounties",
                            emoji="🎯",
                            style=discord.ButtonStyle.success,
                        )
                        btn.callback = self._claim_bounties
                        self.add_item(btn)
                    if invest_ready:
                        btn = discord.ui.Button(
                            label="Collect investment",
                            emoji="📈",
                            style=discord.ButtonStyle.primary,
                        )
                        btn.callback = self._collect_invest
                        self.add_item(btn)
                    if daily_ready:
                        btn = discord.ui.Button(
                            label="Run daily",
                            emoji="🎁",
                            style=discord.ButtonStyle.secondary,
                        )
                        btn.callback = self._run_daily
                        self.add_item(btn)

                async def _claim_bounties(self, btn_i: discord.Interaction):
                    if btn_i.user.id != uid:
                        return await btn_i.response.send_message("This panel is for the requester only.", ephemeral=True)
                    await btn_i.response.defer(ephemeral=True)
                    from commands.economy.bounties import claim_bounties

                    total, count = await claim_bounties(gid, uid)
                    if count:
                        msg = f"Claimed **{format_number(total)}** coins from {count} bounties."
                    else:
                        msg = "No bounties were ready to claim."
                    await btn_i.followup.send(
                        embed=success_embed("Bounties", msg, client=btn_i.client),
                        ephemeral=True,
                    )

                async def _collect_invest(self, btn_i: discord.Interaction):
                    if btn_i.user.id != uid:
                        return await btn_i.response.send_message("This panel is for the requester only.", ephemeral=True)
                    await btn_i.response.defer(ephemeral=True)
                    from commands.economy.invest import collect_matured_investment

                    ok, msg, payout = await collect_matured_investment(gid, uid)
                    if ok:
                        await btn_i.followup.send(
                            embed=success_embed(
                                "Investment collected",
                                f"{msg}\n**+{format_number(payout)}** coins",
                                client=btn_i.client,
                            ),
                            ephemeral=True,
                        )
                    else:
                        await btn_i.followup.send(msg, ephemeral=True)

                async def _run_daily(self, btn_i: discord.Interaction):
                    if btn_i.user.id != uid:
                        return await btn_i.response.send_message("This panel is for the requester only.", ephemeral=True)
                    daily_cmd = command_mention("daily", fallback="`/daily`")
                    await btn_i.response.send_message(
                        f"Run {daily_cmd} to claim your streak reward (bounties auto-claim there too).",
                        ephemeral=True,
                    )

            body = "\n".join(lines) or "Nothing to claim right now."
            from core.help_layout import help_layout_v2_enabled
            from core.claim_layout import ClaimLayout

            if help_layout_v2_enabled():
                try:
                    view = _ClaimHubView()
                    layout = ClaimLayout(
                        body=body,
                        on_bounties=view._claim_bounties if bounty_ready else None,
                        on_invest=view._collect_invest if invest_ready else None,
                        on_daily=view._run_daily if daily_ready else None,
                    )
                    await interaction.followup.send(view=layout, ephemeral=True)
                    return
                except Exception:
                    pass
            await interaction.followup.send(embed=embed, view=_ClaimHubView(), ephemeral=True)
            return

        await interaction.followup.send(embed=embed, ephemeral=True)
