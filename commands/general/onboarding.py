"""First-run onboarding DM (Item 8).

A one-shot DM sent on ``on_member_join`` (when ``onboarding_enabled`` is set
on the guild — default ON) with a small action panel: set timezone, claim
daily, pick notifications, link Steam, done.

Existing welcome flows continue to fire — this DM is additive.
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands

from core.utils import obsidian_embed, success_embed, error_embed, BUTTON_ONLY_RUNNER_MSG
from database import get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)


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

    @discord.ui.button(label="Set Timezone", style=discord.ButtonStyle.primary, emoji="🌐")
    async def tz_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🌐 Set your timezone",
                "Pick a timezone — used for daily reminders, event schedules, and `/me`.",
                category="general",
                client=interaction.client,
            ),
            view=_TimezoneView(self.guild_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Claim Daily", style=discord.ButtonStyle.success, emoji="🎁")
    async def daily_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # We can't run a slash callback directly from a DM context (no guild),
        # so we point the user at the slash command instead.
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🎁 Claim your daily reward",
                f"Hop into **{self.member.guild.name}** and run **`/daily`** "
                "(or `/economy daily`) to claim your first reward.\n\n"
                "_Daily coins reset every 24h UTC. Keep your streak to multiply rewards!_",
                category="economy",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Pick Notifications", style=discord.ButtonStyle.primary, emoji="🔔")
    async def notify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🔔 Pick notifications",
                "In the server, run **`/warframe subscribe`** or look for the "
                "**🔔 Warframe Notification Subscriptions** panel a mod may have posted.\n\n"
                "_You can subscribe to: Baro, Cycles, Archon, Alerts, Invasions, Devstream._",
                category="warframe",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Link Steam", style=discord.ButtonStyle.secondary, emoji="🎮")
    async def steam_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🎮 Link Warframe / Steam",
                "Use **`/warframe link`** in the server to connect your Warframe / "
                "Steam identity for trade pricing, achievement roles, and dojo features.",
                category="warframe",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, emoji="✅")
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
    return obsidian_embed(
        f"👋 Welcome to {member.guild.name}!",
        f"Hi {member.display_name} — here are a few quick things you can set up "
        "to get the most out of the server. Tap a button to start.\n\n"
        "**🌐 Set Timezone** · accurate reminders\n"
        "**🎁 Claim Daily** · start your coin streak\n"
        "**🔔 Pick Notifications** · Baro, alerts, cycles\n"
        "**🎮 Link Steam** · for trading & roles\n\n"
        "_You can re-open this any time with `/onboarding send_me`._",
        category="general",
        client=client,
        brand=True,
        footer="Welcome aboard!",
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

    bot.tree.add_command(onboarding_group)
