"""Economy bounties - daily quests for bonus coins."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, format_number, EMBED_COLORS, render_bar
from database import DB_PATH, now_utc, get_user_balance, add_coins
import aiosqlite

BOUNTY_DEFS = [
    {"id": "daily", "name": "Daily Login", "desc": "Claim your daily reward", "check": "daily", "reward": 25},
    {"id": "earn_100", "name": "Earn 100 Coins", "desc": "Earn 100+ coins today", "check": "earn_100", "reward": 50},
    {"id": "voice_10", "name": "Voice Veteran", "desc": "Spend 10+ minutes in voice", "check": "voice_10", "reward": 40},
    {"id": "lfg_weekly", "name": "Squad Builder", "desc": "Post 2 LFGs this week (Warframe-linked)", "check": "lfg_weekly", "reward": 75},
]


async def _get_bounty_progress(guild_id: int, user_id: int) -> dict:
    """Get progress for each bounty type."""
    today = now_utc().date().isoformat()
    week_start = (now_utc().date() - timedelta(days=now_utc().weekday())).isoformat()
    result = {"daily": False, "earn_100": 0, "voice_10": 0, "lfg_weekly": 0}
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM daily_claims WHERE guild_id=? AND user_id=? AND last_claim_date=?",
            (guild_id, user_id, today),
        )
        result["daily"] = await cur.fetchone() is not None
        cur = await db.execute(
            """SELECT COALESCE(SUM(amount), 0) FROM economy_transactions
               WHERE guild_id=? AND user_id=? AND date(created_at)=? AND amount>0""",
            (guild_id, user_id, today),
        )
        row = await cur.fetchone()
        result["earn_100"] = row[0] if row else 0
        cur = await db.execute(
            """SELECT COALESCE(SUM(amount), 0) FROM economy_transactions
               WHERE guild_id=? AND user_id=? AND date(created_at)=? AND transaction_type='VOICE'""",
            (guild_id, user_id, today),
        )
        row = await cur.fetchone()
        voice_coins = row[0] if row else 0
        from core.config import COINS_PER_MINUTE_VOICE
        result["voice_10"] = int(voice_coins / COINS_PER_MINUTE_VOICE) if COINS_PER_MINUTE_VOICE else 0
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM lfg_posts
            WHERE guild_id=? AND creator_id=? AND date(created_at) >= ?
            """,
            (guild_id, user_id, week_start),
        )
        result["lfg_weekly"] = int((await cur.fetchone())[0] or 0)
    return result


_BOUNTY_TARGETS = {"daily": 1, "earn_100": 100, "voice_10": 10, "lfg_weekly": 2}


def _bounty_done(bid: str, progress: dict) -> bool:
    """Whether a bounty's completion requirement is met."""
    if bid == "daily":
        return bool(progress.get("daily"))
    if bid == "earn_100":
        return progress.get("earn_100", 0) >= 100
    if bid == "lfg_weekly":
        return progress.get("lfg_weekly", 0) >= 2
    if bid == "voice_10":
        return progress.get("voice_10", 0) >= 10
    return False


async def get_claimable_bounties(guild_id: int, user_id: int) -> list[dict]:
    """Bounties that are complete and not yet claimed today."""
    progress = await _get_bounty_progress(guild_id, user_id)
    today = now_utc().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT bounty_type FROM economy_bounties WHERE guild_id=? AND user_id=? "
            "AND date(created_at)=? AND claimed=1",
            (guild_id, user_id, today),
        )
        claimed = {r[0] for r in await cur.fetchall()}
    return [b for b in BOUNTY_DEFS if b["id"] not in claimed and _bounty_done(b["id"], progress)]


async def claim_bounties(guild_id: int, user_id: int) -> tuple[int, int]:
    """Claim all completed-unclaimed bounties. Returns (total_coins, count)."""
    to_claim = await get_claimable_bounties(guild_id, user_id)
    if not to_claim:
        return (0, 0)
    total = sum(b["reward"] for b in to_claim)
    bonus = 0
    if len(to_claim) >= len(BOUNTY_DEFS):
        bonus = 25
        total += bonus
    await add_coins(guild_id, user_id, total, "BOUNTY", "Daily bounties")
    async with aiosqlite.connect(DB_PATH) as db:
        for b in to_claim:
            tgt = _BOUNTY_TARGETS.get(b["id"], 1)
            await db.execute(
                """INSERT INTO economy_bounties (guild_id, user_id, bounty_type, progress, target, reward, claimed, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(guild_id, user_id, bounty_type) DO UPDATE SET claimed=1, progress=excluded.progress""",
                (guild_id, user_id, b["id"], tgt, tgt, b["reward"], now_utc().isoformat()),
            )
        await db.commit()
    return (total, len(to_claim))


def setup(bot, group=None):
    cmd = group.command(name="bounties", description="View and claim daily bounties for bonus coins.") if group else bot.tree.command(name="bounties", description="View daily bounties.")

    @cmd
    async def bounties(interaction: discord.Interaction):
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            from core.reply_helpers import reply_server_only
            return await reply_server_only(interaction)
        await interaction.response.defer(ephemeral=True)
        uid = interaction.user.id
        gid = interaction.guild.id
        progress = await _get_bounty_progress(gid, uid)
        today = now_utc().date().isoformat()

        lines = []
        claimed_any = False
        total_reward = 0

        # Pre-fetch claim statuses in one query
        claimed_set: set = set()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT bounty_type FROM economy_bounties WHERE guild_id=? AND user_id=? AND date(created_at)=? AND claimed=1",
                (gid, uid, today),
            )
            claimed_set = {r[0] for r in await cur.fetchall()}

        for b in BOUNTY_DEFS:
            bid = b["id"]
            target_val = {
                "daily": 1, "earn_100": 100, "voice_10": 10, "lfg_weekly": 2,
            }.get(bid, 1)
            if bid == "daily":
                current_val = 1 if progress["daily"] else 0
            elif bid == "earn_100":
                current_val = min(int(progress["earn_100"]), 100)
            elif bid == "lfg_weekly":
                current_val = min(int(progress["lfg_weekly"]), 2)
            else:
                current_val = min(int(progress["voice_10"]), 10)

            done = current_val >= target_val
            already_claimed = bid in claimed_set

            pct = int(100 * current_val / target_val) if target_val > 0 else 0
            bar = render_bar(pct, length=10, show_pct=False)

            if already_claimed:
                status_line = f"✅ **Claimed**  {bar} 100%"
                claimed_any = True
            elif done:
                status_line = f"✅ **Complete** — use **Claim** below  {bar} 100%"
                total_reward += b["reward"]
            else:
                if bid == "daily":
                    progress_label = "0/1"
                elif bid == "earn_100":
                    progress_label = f"{format_number(current_val)}/100 coins"
                elif bid == "lfg_weekly":
                    progress_label = f"{current_val}/2 LFGs"
                else:
                    progress_label = f"{current_val}/10 min"
                status_line = f"{bar} {progress_label}"

            lines.append(
                f"**{b['name']}** · 🎁 {b['reward']} coins\n"
                f"{status_line}\n"
                f"-# {b['desc']}"
            )
        desc = "\n\n".join(lines)
        from core.first_run_nudge import maybe_first_run_hint
        desc = await maybe_first_run_hint(gid, uid, desc, feature="bounties")
        embed = embed_template(
            "showcase",
            "Daily Bounties",
            desc or "_No bounties available right now — check back after reset._",
            category="economy",
            footer=footer_for("economy_daily") + " · Claim completed bounties below",
            client=interaction.client,
        )
        view = None
        if total_reward > 0:
            from discord.ui import View, Button
            class ClaimView(View):
                def __init__(self, reward_total, **kwargs):
                    super().__init__(timeout=60, **kwargs)
                    self.reward_total = reward_total
                @discord.ui.button(label=f"Claim {total_reward} coins", style=discord.ButtonStyle.primary, emoji="🎁")
                async def claim_btn(self, btn_i: discord.Interaction, btn: Button):
                    if btn_i.user.id != interaction.user.id:
                        return await btn_i.response.send_message("Only for you.", ephemeral=True)
                    await btn_i.response.defer(ephemeral=True)
                    total, count = await claim_bounties(gid, uid)
                    if not count:
                        return await btn_i.followup.send("Nothing to claim.", ephemeral=True)
                    for c in self.children:
                        c.disabled = True
                    try:
                        await btn_i.message.edit(view=self)
                    except Exception:
                        pass
                    await btn_i.followup.send(
                        embed=obsidian_embed("Bounties Claimed!", f"**+{format_number(total)}** coins!", color=EMBED_COLORS["success"], client=interaction.client),
                        ephemeral=True,
                    )
            view = ClaimView(total_reward)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
