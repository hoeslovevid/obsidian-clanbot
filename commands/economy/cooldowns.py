"""/economy cooldowns — a single view of the user's active cooldowns."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

from core.utils import obsidian_embed, EMBED_COLORS
from core.config import MESSAGE_COOLDOWN_SECONDS
from core.db import open_db
from database import now_utc


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def setup(bot, group=None):
    decorator = (
        group.command(name="cooldowns", description="See your daily, message, and investment cooldowns at a glance.")
        if group
        else bot.tree.command(name="cooldowns", description="See your cooldowns at a glance.")
    )

    @decorator
    async def cooldowns(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used inside a server.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)

        from core.command_mentions import command_mention

        gid = interaction.guild.id
        uid = interaction.user.id
        lines: list[str] = []

        # --- Daily reward -----------------------------------------------------
        today = datetime.now(timezone.utc).date().isoformat()
        async with open_db() as db:
            cur = await db.execute(
                "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
                (gid, uid),
            )
            row = await cur.fetchone()
        if row and row[0] == today:
            tomorrow = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            lines.append(f"🎁 **Daily reward** — ready <t:{int(tomorrow.timestamp())}:R>")
        else:
            lines.append(f"🎁 **Daily reward** — ✅ ready now · {command_mention('daily', fallback='`/daily`')}")

        # --- Message economy cooldown ----------------------------------------
        async with open_db() as db:
            cur = await db.execute(
                "SELECT last_message_at FROM message_cooldowns WHERE guild_id=? AND user_id=?",
                (gid, uid),
            )
            row = await cur.fetchone()
        msg_ready = True
        if row and row[0]:
            last = _parse_iso(row[0])
            if last:
                nxt = last + timedelta(seconds=MESSAGE_COOLDOWN_SECONDS)
                if nxt > now_utc():
                    lines.append(f"💬 **Message reward** — next <t:{int(nxt.timestamp())}:R>")
                    msg_ready = False
        if msg_ready:
            lines.append("💬 **Message reward** — ✅ ready (just chat)")

        # --- Investment maturity ---------------------------------------------
        async with open_db() as db:
            cur = await db.execute(
                "SELECT maturity_date FROM investments WHERE guild_id=? AND user_id=? AND collected=0 "
                "ORDER BY maturity_date ASC LIMIT 1",
                (gid, uid),
            )
            row = await cur.fetchone()
        if row and row[0]:
            mat = _parse_iso(row[0])
            if mat and mat <= now_utc():
                lines.append(
                    f"📈 **Investment** — ✅ matured · {command_mention('economy invest_status', fallback='`/economy invest_status`')}"
                )
            elif mat:
                lines.append(f"📈 **Investment** — matures <t:{int(mat.timestamp())}:R>")

        embed = obsidian_embed(
            "⏳ Your Cooldowns",
            "\n".join(lines),
            color=EMBED_COLORS.get("economy", EMBED_COLORS.get("general", discord.Color.blue())),
            footer="Times update live as cooldowns expire",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
