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


async def _run_cooldowns(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            "This command can only be used inside a server.", ephemeral=True
        )
    gid = interaction.guild.id
    uid = interaction.user.id
    from core.user_prefs import results_ephemeral

    defer_ephemeral = await results_ephemeral(gid, uid, default=True)
    await interaction.response.defer(ephemeral=defer_ephemeral)

    from core.command_mentions import command_mention
    lines: list[str] = []

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
                f"📈 **Investment** — ✅ matured · "
                f"{command_mention('economy invest_collect', fallback='`/economy invest_collect`')}"
            )
        elif mat:
            lines.append(f"📈 **Investment** — matures <t:{int(mat.timestamp())}:R>")

    try:
        from commands.economy.bounties import _get_bounty_progress, BOUNTY_DEFS

        prog = await _get_bounty_progress(gid, uid)
        async with open_db() as db:
            cur = await db.execute(
                "SELECT bounty_type FROM economy_bounties WHERE guild_id=? AND user_id=? "
                "AND date(created_at)=? AND claimed=1",
                (gid, uid, today),
            )
            claimed = {r[0] for r in await cur.fetchall()}
        ready = 0
        for b in BOUNTY_DEFS:
            bid = b["id"]
            if bid in claimed:
                continue
            if bid == "daily":
                done = bool(prog.get("daily"))
            elif bid == "earn_100":
                done = prog.get("earn_100", 0) >= 100
            elif bid == "lfg_weekly":
                done = prog.get("lfg_weekly", 0) >= 2
            else:
                done = prog.get("voice_10", 0) >= 10
            if done:
                ready += 1
        midnight = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        if ready:
            lines.append(
                f"🎯 **Bounties** — {ready} ready · "
                f"{command_mention('claim', fallback='`/claim`')}"
            )
        else:
            lines.append(f"🎯 **Bounties** — reset <t:{int(midnight.timestamp())}:R>")
    except Exception:
        pass

    lines.append("🎲 **Gambling** — no per-bet cooldown")

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
                lines.append(
                    f"🐾 **{pet[5] or 'Pet'}** — needs care · "
                    f"{command_mention('economy pets', fallback='`/economy pets`')}"
                )
            else:
                lines.append(f"🐾 **{pet[5] or 'Pet'}** — ✅ doing fine")
    except Exception:
        pass

    from core.embed_prefs import embed_kwargs

    embed = obsidian_embed(
        "⏳ Your Cooldowns",
        "\n".join(lines),
        color=EMBED_COLORS.get("economy", EMBED_COLORS.get("general", discord.Color.blue())),
        footer="Times update live as cooldowns expire",
        client=interaction.client,
        **await embed_kwargs(gid, uid),
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot, group=None):
    if group:
        group.command(
            name="cooldowns",
            description="See your daily, message, and investment cooldowns at a glance.",
        )(_run_cooldowns)
    shortcut = app_commands.Command(
        name="cooldowns",
        description="Your cooldowns at a glance (shortcut for /economy cooldowns).",
        callback=_run_cooldowns,
    )
    try:
        bot.tree.add_command(shortcut)
    except Exception:
        pass
