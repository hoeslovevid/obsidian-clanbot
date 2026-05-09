"""Economy bounties - daily quests for bonus coins."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, format_number, EMBED_COLORS, render_bar
from database import DB_PATH, now_utc, get_user_balance, add_coins
import aiosqlite

BOUNTY_DEFS = [
    {"id": "daily", "name": "Daily Login", "desc": "Claim your daily reward", "check": "daily", "reward": 25},
    {"id": "earn_100", "name": "Earn 100 Coins", "desc": "Earn 100+ coins today", "check": "earn_100", "reward": 50},
    {"id": "voice_10", "name": "Voice Veteran", "desc": "Spend 10+ minutes in voice", "check": "voice_10", "reward": 40},
]


async def _get_bounty_progress(guild_id: int, user_id: int) -> dict:
    """Get progress for each bounty type."""
    today = now_utc().date().isoformat()
    result = {"daily": False, "earn_100": 0, "voice_10": 0}
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
    return result


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
            return await interaction.response.send_message("Server only.", ephemeral=True)
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
            target_val = 1 if bid == "daily" else (100 if bid == "earn_100" else 10)
            if bid == "daily":
                current_val = 1 if progress["daily"] else 0
            elif bid == "earn_100":
                current_val = min(int(progress["earn_100"]), 100)
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
                else:
                    progress_label = f"{current_val}/10 min"
                status_line = f"{bar} {progress_label}"

            lines.append(
                f"**{b['name']}** · 🎁 {b['reward']} coins\n"
                f"{status_line}\n"
                f"-# {b['desc']}"
            )
        desc = "\n\n".join(lines)
        embed = obsidian_embed(
            "Daily Bounties",
            desc or "No bounties today.",
            color=EMBED_COLORS["economy"],
            footer="Reset daily • Claim completed bounties below",
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
                    prog = await _get_bounty_progress(gid, uid)
                    to_claim = []
                    for b in BOUNTY_DEFS:
                        bid = b["id"]
                        done = prog["daily"] if bid == "daily" else (prog["earn_100"] >= 100 if bid == "earn_100" else prog["voice_10"] >= 10)
                        if not done:
                            continue
                        async with aiosqlite.connect(DB_PATH) as db:
                            cur = await db.execute(
                                "SELECT 1 FROM economy_bounties WHERE guild_id=? AND user_id=? AND bounty_type=? AND date(created_at)=? AND claimed=1",
                                (gid, uid, bid, today),
                            )
                            if await cur.fetchone() is None:
                                to_claim.append(b)
                    if not to_claim:
                        return await btn_i.followup.send("Nothing to claim.", ephemeral=True)
                    total = sum(b["reward"] for b in to_claim)
                    await add_coins(gid, uid, total, "BOUNTY", "Daily bounties")
                    async with aiosqlite.connect(DB_PATH) as db:
                        for b in to_claim:
                            tgt = 100 if b["id"] == "earn_100" else (10 if b["id"] == "voice_10" else 1)
                            prog = tgt
                            await db.execute(
                                """INSERT INTO economy_bounties (guild_id, user_id, bounty_type, progress, target, reward, claimed, created_at)
                                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                                   ON CONFLICT(guild_id, user_id, bounty_type) DO UPDATE SET claimed=1, progress=excluded.progress""",
                                (gid, uid, b["id"], prog, tgt, b["reward"], now_utc().isoformat()),
                            )
                        await db.commit()
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
