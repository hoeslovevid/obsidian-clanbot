"""First-run onboarding DM (Item 8).

A one-shot DM sent on ``on_member_join`` (when ``onboarding_enabled`` is set
on the guild — default ON) with a small action panel: set timezone, claim
daily, pick notifications, link Steam, done.

Existing welcome flows continue to fire — this DM is additive.

Item 81 also adds a small ``onboarding_steps`` ledger so mods can pull
funnel stats with ``/tools onboarding_stats``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiosqlite  # type: ignore
import discord
from discord import app_commands

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import (
    obsidian_embed, success_embed, error_embed, BUTTON_ONLY_RUNNER_MSG,
    EMBED_COLORS, render_bar, is_mod, format_number,
)
from database import DB_PATH, get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Item 81 — onboarding step ledger
# ---------------------------------------------------------------------------
ONBOARDING_STEP_NAMES: tuple[str, ...] = (
    "set_timezone", "set_platform", "open_menu",
)


async def _ensure_onboarding_steps_table() -> None:
    """Lazy CREATE so the table appears the first time a step is recorded."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS onboarding_steps (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                step_name TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, step_name)
            )
            """
        )
        await db.commit()


async def get_user_onboarding_progress(guild_id: int, user_id: int) -> tuple[int, dict[str, bool]]:
    """Return (completed_count, step_name -> done) for a member."""
    await _ensure_onboarding_steps_table()
    completed = {step: False for step in ONBOARDING_STEP_NAMES}
    async with aiosqlite.connect(DB_PATH) as db:
        for step in ONBOARDING_STEP_NAMES:
            cur = await db.execute(
                "SELECT 1 FROM onboarding_steps WHERE guild_id=? AND user_id=? AND step_name=?",
                (guild_id, user_id, step),
            )
            completed[step] = bool(await cur.fetchone())
    return sum(completed.values()), completed


async def _record_onboarding_step(guild_id: int, user_id: int, step_name: str) -> None:
    """Record (idempotently) that ``user_id`` completed ``step_name``."""
    if step_name not in ONBOARDING_STEP_NAMES:
        return
    try:
        await _ensure_onboarding_steps_table()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO onboarding_steps (guild_id, user_id, step_name, completed_at) "
                "VALUES (?, ?, ?, ?)",
                (guild_id, user_id, step_name, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
    except Exception as e:
        logger.debug(f"[onboarding] could not record step {step_name}: {e}")


# ---------------------------------------------------------------------------
# Timezone select (subset of COMMON_TIMEZONES — keep ≤ 25 options for select)
# ---------------------------------------------------------------------------
def _tz_options() -> list[discord.SelectOption]:
    # Import inside to avoid an import cycle at module load.
    from commands.general.preferences import COMMON_TIMEZONES
    return [discord.SelectOption(label=label, value=tz) for tz, label in COMMON_TIMEZONES[:25]]


class _TimezoneSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        super().__init__(
            placeholder="Pick your timezone…",
            options=_tz_options(),
            min_values=1,
            max_values=1,
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        tz = self.values[0]
        try:
            from database import set_user_timezone
            await set_user_timezone(self.guild_id, interaction.user.id, tz)
        except Exception as e:
            return await interaction.response.send_message(
                embed=error_embed("Couldn't save timezone", str(e), client=interaction.client),
                ephemeral=True,
            )
        await _record_onboarding_step(self.guild_id, interaction.user.id, "set_timezone")
        await interaction.response.send_message(
            embed=success_embed(
                "Timezone Saved",
                f"Reminders and events will use **{tz}**. Change anytime with `/general preferences`.",
                client=interaction.client,
            ),
            ephemeral=True,
        )


class _TimezoneView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.add_item(_TimezoneSelect(guild_id))


class OnboardingView(discord.ui.View):
    """Per-user onboarding panel (3-minute timeout). Not persistent — runs once."""

    def __init__(self, member: discord.Member, *, guild_id: int):
        super().__init__(timeout=300)
        self.member = member
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="1 · Timezone", style=discord.ButtonStyle.primary, emoji="🌐")
    async def tz_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=embed_template(
                "showcase",
                "🌐 Set your timezone",
                "Pick a timezone — used for reminders, events, and `/me`.\n\n"
                "You can also run **`/preferences`** anytime.",
                category="general",
                client=interaction.client,
            ),
            view=_TimezoneView(self.guild_id),
            ephemeral=True,
        )

    @discord.ui.button(label="2 · Platform", style=discord.ButtonStyle.primary, emoji="🎮")
    async def platform_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _record_onboarding_step(self.guild_id, interaction.user.id, "set_platform")
        await interaction.response.send_message(
            embed=embed_template(
                "showcase",
                "🎮 Warframe platform",
                f"In **{self.member.guild.name}**, run **`/preferences`** and set your platform "
                "(PC, Xbox, PlayStation, Switch).\n\n"
                "_Baro, fissures, and trade tools follow this preference._",
                category="warframe",
                footer=footer_for("warframe_status"),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="3 · Menu", style=discord.ButtonStyle.success, emoji="📋")
    async def menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _record_onboarding_step(self.guild_id, interaction.user.id, "open_menu")
        await interaction.response.send_message(
            embed=embed_template(
                "showcase",
                "📋 Command menu",
                f"Use **`/menu`** in the server for daily, profile, baro, tickets, and more.\n\n"
                "Pin favorites with **`/favorite_add`** — they appear at the top of `/menu` and `/help`.",
                category="general",
                footer=footer_for("help"),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, emoji="✅", row=1)
    async def done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        await interaction.followup.send(
            "You're all set — `/help` is always there if you forget anything.",
            ephemeral=True,
        )
        self.stop()


def _build_dm_embed(member: discord.Member, client) -> discord.Embed:
    return embed_template(
        "showcase",
        f"👋 Welcome to {member.guild.name}!",
        f"Hi {member.display_name} — tap a button to get started:\n\n"
        "**1.** Timezone · **2.** Platform (`/preferences`) · **3.** `/menu` quick picks\n\n"
        "_Re-open anytime with `/onboarding resume`._",
        category="general",
        client=client,
        footer=footer_for("onboarding"),
    )


async def send_onboarding_dm(member: discord.Member, bot) -> bool:
    """Try to DM the onboarding panel to ``member``. Returns True when sent.

    Caller is responsible for gating by ``onboarding_enabled`` and
    ``onboarding_sent:{user_id}``; this function only handles DM mechanics.
    """
    try:
        embed = _build_dm_embed(member, bot)
        view = OnboardingView(member, guild_id=member.guild.id)
        await member.send(embed=embed, view=view)
        return True
    except discord.Forbidden:
        return False
    except Exception as e:
        logger.debug(f"[onboarding] DM failed for {member.id}: {e}")
        return False


async def maybe_send_onboarding_on_join(member: discord.Member, bot) -> None:
    """Hook for ``on_member_join``: send the DM unless disabled / already sent."""
    if member.bot:
        return
    try:
        enabled = await get_guild_setting(member.guild.id, "onboarding_enabled")
        # Default ON: only treat an explicit "0" as opt-out.
        if enabled == "0":
            return
        already = await get_guild_setting(member.guild.id, f"onboarding_sent:{member.id}")
        if already == "1":
            return
        sent = await send_onboarding_dm(member, bot)
        if sent:
            await set_guild_setting(member.guild.id, f"onboarding_sent:{member.id}", "1")
    except Exception as e:
        logger.debug(f"[onboarding] hook error: {e}")


def setup(bot, group=None):
    """Register the user-facing ``/onboarding send_me`` command."""
    # Use a dedicated top-level group so the command path stays short and
    # discoverable; this lives outside the existing 25-cmd-limited groups.
    onboarding_group = app_commands.Group(name="onboarding", description="🌟 First-run onboarding panel.")

    @onboarding_group.command(name="resume", description="See onboarding progress and continue where you left off.")
    async def resume(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Member context required.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        done_count, completed = await get_user_onboarding_progress(interaction.guild.id, interaction.user.id)
        total = len(ONBOARDING_STEP_NAMES)
        pct = (100.0 * done_count / total) if total else 0.0
        step_lines: list[str] = []
        for step in ONBOARDING_STEP_NAMES:
            mark = "✅" if completed[step] else "⬜"
            label = step.replace("_", " ").title()
            step_lines.append(f"{mark} **{label}**")
        remaining = [s.replace("_", " ").title() for s in ONBOARDING_STEP_NAMES if not completed[s]]
        footer = "All steps complete — nice work!" if done_count >= total else f"Next up: **{remaining[0]}**"
        embed = obsidian_embed(
            "🌟 Onboarding Progress",
            f"{render_bar(pct, length=12)} · **{done_count}/{total}** steps\n\n" + "\n".join(step_lines),
            category="general",
            footer=footer,
            client=interaction.client,
        )
        view = OnboardingView(interaction.user, guild_id=interaction.guild.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @onboarding_group.command(name="send_me", description="DM yourself the onboarding panel.")
    async def send_me(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Member context required.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        ok = await send_onboarding_dm(interaction.user, interaction.client)
        if not ok:
            return await interaction.followup.send(
                embed=error_embed(
                    "Couldn't DM you",
                    "I couldn't send you a DM — make sure direct messages from server members are enabled, then try again.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.followup.send(
            embed=success_embed("Onboarding sent!", "Check your DMs.", client=interaction.client),
            ephemeral=True,
        )

    @onboarding_group.command(name="server_toggle", description="(mods) Toggle the first-join onboarding DM for this server.")
    @app_commands.describe(state="Turn the onboarding DM on or off for new members.")
    @app_commands.choices(state=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    async def server_toggle(interaction: discord.Interaction, state: app_commands.Choice[str]):
        from core.utils import is_mod
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed(
                    "Permission Denied",
                    "Only administrators can toggle onboarding DMs.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await set_guild_setting(interaction.guild.id, "onboarding_enabled", state.value)
        await interaction.response.send_message(
            embed=success_embed(
                "Onboarding Updated",
                f"First-join onboarding DM is now **{'ON' if state.value == '1' else 'OFF'}**.",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # Item 81 — onboarding stats. The brief asks for `/tools onboarding_stats`,
    # but `tools_group` is currently at the 25-subcommand cap (favorites +
    # phishing already overflow), so when full we fall back to attaching a
    # `stats` subcommand to the existing `/onboarding` group instead.
    async def _show_onboarding_stats(interaction: discord.Interaction, days: int):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Server only.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Mods only.", client=interaction.client),
                ephemeral=True,
            )
        days = max(1, min(365, int(days or 30)))
        await interaction.response.defer(ephemeral=True)
        await _ensure_onboarding_steps_table()

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM onboarding_steps "
                "WHERE guild_id=? AND completed_at >= ?",
                (interaction.guild.id, cutoff),
            )
            total_users_row = await cur.fetchone()
            total_users = int(total_users_row[0]) if total_users_row else 0

            step_counts: dict[str, int] = {}
            for step in ONBOARDING_STEP_NAMES:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM onboarding_steps "
                    "WHERE guild_id=? AND step_name=? AND completed_at >= ?",
                    (interaction.guild.id, step, cutoff),
                )
                r = await cur.fetchone()
                step_counts[step] = int(r[0]) if r else 0

        denominator = max(total_users, 1)
        funnel_lines: list[str] = []
        for step in ONBOARDING_STEP_NAMES:
            count = step_counts.get(step, 0)
            pct = 100.0 * count / denominator if total_users else 0.0
            label = step.replace("_", " ").title()
            funnel_lines.append(f"**{label}** — {format_number(count)}/{format_number(total_users)}\n{render_bar(pct)}")

        # Top drop-off step = the step that loses the most users vs. its predecessor.
        ordered_pcts = [
            (step, (100.0 * step_counts.get(step, 0) / denominator) if total_users else 0.0)
            for step in ONBOARDING_STEP_NAMES
        ]
        biggest_drop_step: Optional[str] = None
        biggest_drop_value = 0.0
        for prev, curr in zip(ordered_pcts, ordered_pcts[1:]):
            drop = prev[1] - curr[1]
            if drop > biggest_drop_value:
                biggest_drop_value = drop
                biggest_drop_step = curr[0]
        drop_off_line = (
            f"**{biggest_drop_step.replace('_', ' ').title()}** "
            f"(−{biggest_drop_value:.0f}% from previous step)"
            if biggest_drop_step else "—"
        )

        fields = [
            ("👥 Onboarded users", f"**{format_number(total_users)}** in last **{days}** days", False),
            ("📊 Funnel", "\n\n".join(funnel_lines), False),
            ("📉 Top drop-off", drop_off_line, False),
        ]
        await interaction.followup.send(
            embed=obsidian_embed(
                "🌟 Onboarding Stats",
                f"Per-step completion for **{interaction.guild.name}**.",
                color=EMBED_COLORS["community"],
                fields=fields,
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # `tools_group` is at its 25-subcommand cap (favorites + phishing already
    # overflow), so the stats command is always attached to the dedicated
    # `/onboarding` group as `/onboarding stats`.
    @onboarding_group.command(name="stats", description="(mods) Onboarding completion funnel for the last N days.")
    @app_commands.describe(days="Window in days to summarise (default 30, max 365).")
    async def _onboarding_stats_self(interaction: discord.Interaction, days: int = 30):
        await _show_onboarding_stats(interaction, days)

    bot.tree.add_command(onboarding_group)
