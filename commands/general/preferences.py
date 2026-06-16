"""User and guild preferences (timezone, quieter mode)."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, success_embed, error_embed, is_mod, EMBED_COLORS
from database import (
    get_user_timezone, set_user_timezone, get_user_platform, set_user_platform,
    get_quieter_mode, set_quieter_mode, get_digest_dm, set_digest_dm,
    get_achievement_notify_style, set_achievement_notify_style, get_guild_setting, set_guild_setting,
)
from core.user_time import get_user_time_format

COMMON_TIMEZONES = [
    ("UTC", "UTC"),
    ("America/New_York", "Eastern"),
    ("America/Chicago", "Central"),
    ("America/Denver", "Mountain"),
    ("America/Los_Angeles", "Pacific"),
    ("Europe/London", "UK"),
    ("Europe/Paris", "Central Europe"),
    ("Asia/Tokyo", "Japan"),
    ("Australia/Sydney", "Australia East"),
    ("America/Toronto", "Toronto"),
    ("America/Sao_Paulo", "São Paulo"),
    ("Europe/Berlin", "Berlin"),
    ("Europe/Moscow", "Moscow"),
    ("Asia/Shanghai", "China"),
    ("Asia/Seoul", "Korea"),
    ("Asia/Kolkata", "India"),
]

PLATFORM_CHOICES = [
    app_commands.Choice(name="PC", value="pc"),
    app_commands.Choice(name="Xbox", value="xbox"),
    app_commands.Choice(name="PlayStation", value="ps4"),
    app_commands.Choice(name="Switch", value="switch"),
    app_commands.Choice(name="(clear)", value="-"),
]


def setup(bot, group=None):
    """Register preferences command."""
    command_decorator = group.command(name="preferences", description="Set your timezone or view server preferences.") if group else bot.tree.command(name="preferences", description="Set your timezone or view server preferences.")

    @command_decorator
    @app_commands.describe(
        timezone="Your timezone (used for reminders and event times)",
        platform="Trading platform (used by /trading trade_price when not specified)",
        quieter="Enable quieter mode: fewer pings in events/reminders (mods only)",
        daily_reminder="Get a DM ~1 hour before your daily streak resets",
        levelup_dm="Get a DM (instead of a public post) when you level up",
        achievement_notify="Show a private notification when you unlock an achievement (legacy on/off)",
        achievement_notify_style="How achievement unlocks are announced",
        digest_dm="Daily DM digest: unclaimed daily, Baro window, today's events",
        time_format="Clock display preference for timestamps",
        investment_dm="Get a DM when your investment matures and is ready to collect",
        typo_helper="Reply with a slash-command suggestion when you mis-type one in chat",
        hide_leaderboards="Show as Hidden on coin, XP, voice, and achievement leaderboards",
        private_results="Make your personal results (e.g. /profile, /me) private to you by default",
    )
    @app_commands.choices(timezone=[
        app_commands.Choice(name=label, value=tz) for tz, label in COMMON_TIMEZONES
    ])
    @app_commands.choices(platform=PLATFORM_CHOICES)
    @app_commands.choices(quieter=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    @app_commands.choices(daily_reminder=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    @app_commands.choices(levelup_dm=[
        app_commands.Choice(name="On (DM)", value="1"),
        app_commands.Choice(name="Off (public channel)", value="0"),
    ])
    @app_commands.choices(achievement_notify=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    @app_commands.choices(achievement_notify_style=[
        app_commands.Choice(name="Ephemeral (private reply)", value="ephemeral"),
        app_commands.Choice(name="Public channel", value="channel"),
        app_commands.Choice(name="DM", value="dm"),
        app_commands.Choice(name="Off", value="off"),
    ])
    @app_commands.choices(digest_dm=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    @app_commands.choices(time_format=[
        app_commands.Choice(name="12-hour", value="12"),
        app_commands.Choice(name="24-hour", value="24"),
    ])
    @app_commands.choices(investment_dm=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    @app_commands.choices(typo_helper=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    @app_commands.choices(hide_leaderboards=[
        app_commands.Choice(name="On (hidden)", value="1"),
        app_commands.Choice(name="Off (show name)", value="0"),
    ])
    @app_commands.choices(private_results=[
        app_commands.Choice(name="On (private to me)", value="1"),
        app_commands.Choice(name="Off (default visibility)", value="0"),
    ])
    async def preferences(
        interaction: discord.Interaction,
        timezone: Optional[app_commands.Choice[str]] = None,
        platform: Optional[app_commands.Choice[str]] = None,
        quieter: Optional[app_commands.Choice[str]] = None,
        daily_reminder: Optional[app_commands.Choice[str]] = None,
        levelup_dm: Optional[app_commands.Choice[str]] = None,
        achievement_notify: Optional[app_commands.Choice[str]] = None,
        achievement_notify_style: Optional[app_commands.Choice[str]] = None,
        digest_dm: Optional[app_commands.Choice[str]] = None,
        time_format: Optional[app_commands.Choice[str]] = None,
        investment_dm: Optional[app_commands.Choice[str]] = None,
        typo_helper: Optional[app_commands.Choice[str]] = None,
        hide_leaderboards: Optional[app_commands.Choice[str]] = None,
        private_results: Optional[app_commands.Choice[str]] = None,
    ):
        """Set timezone or quieter mode."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used inside a server.", client=interaction.client),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        lines = []
        updated = []

        if timezone:
            tz_val = timezone.value
            await set_user_timezone(interaction.guild.id, interaction.user.id, tz_val)
            updated.append(f"**Timezone:** {tz_val}")

        if platform and platform.value != "-":
            await set_user_platform(interaction.guild.id, interaction.user.id, platform.value)
            updated.append(f"**Trading platform:** {platform.value.upper()}")
        elif platform and platform.value == "-":
            await set_user_platform(interaction.guild.id, interaction.user.id, "")
            updated.append("**Trading platform:** cleared (defaults to PC)")

        if quieter:
            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                lines.append("⚠️ Only moderators can change quieter mode.")
            else:
                enabled = quieter.value == "1"
                await set_quieter_mode(interaction.guild.id, enabled)
                updated.append(f"**Quieter mode:** {'On' if enabled else 'Off'}")

        if daily_reminder:
            from database import set_guild_setting
            await set_guild_setting(interaction.guild.id, f"user_daily_reminder:{interaction.user.id}", daily_reminder.value)
            state = "On" if daily_reminder.value == "1" else "Off"
            updated.append(f"**Daily streak reminder:** {state}")

        if levelup_dm:
            from database import set_guild_setting
            await set_guild_setting(interaction.guild.id, f"user_levelup_dm:{interaction.user.id}", levelup_dm.value)
            state = "On (DM)" if levelup_dm.value == "1" else "Off (public)"
            updated.append(f"**Level-up notification:** {state}")

        if achievement_notify_style:
            await set_achievement_notify_style(
                interaction.guild.id, interaction.user.id, achievement_notify_style.value
            )
            labels = {
                "ephemeral": "Ephemeral (private reply)",
                "channel": "Public channel",
                "dm": "DM",
                "off": "Off",
            }
            updated.append(
                f"**Achievement notifications:** {labels.get(achievement_notify_style.value, achievement_notify_style.value)}"
            )
        elif achievement_notify:
            style = "ephemeral" if achievement_notify.value == "1" else "off"
            await set_achievement_notify_style(interaction.guild.id, interaction.user.id, style)
            state = "On" if achievement_notify.value == "1" else "Off"
            updated.append(f"**Achievement notifications:** {state}")

        if digest_dm:
            enabled = digest_dm.value == "1"
            await set_digest_dm(interaction.guild.id, interaction.user.id, enabled)
            updated.append(f"**Daily digest DM:** {'On ☀️' if enabled else 'Off'}")

        if time_format:
            await set_guild_setting(
                interaction.guild.id,
                f"user_time_format:{interaction.user.id}",
                time_format.value,
            )
            updated.append(f"**Time format:** {'24-hour' if time_format.value == '24' else '12-hour'}")

        if investment_dm:
            from database import set_guild_setting
            await set_guild_setting(interaction.guild.id, f"user_investment_dm:{interaction.user.id}", investment_dm.value)
            state = "On" if investment_dm.value == "1" else "Off"
            updated.append(f"**Investment maturity DM:** {state}")

        if typo_helper:
            from database import set_guild_setting
            # Stored under user_typo_helper:{uid}; "0" = off, anything else = on (default).
            await set_guild_setting(interaction.guild.id, f"user_typo_helper:{interaction.user.id}", typo_helper.value)
            state = "On" if typo_helper.value == "1" else "Off"
            updated.append(f"**Typo helper:** {state}")

        if hide_leaderboards:
            from database import set_guild_setting
            await set_guild_setting(
                interaction.guild.id,
                f"user_hide_leaderboards:{interaction.user.id}",
                hide_leaderboards.value,
            )
            state = "On (hidden)" if hide_leaderboards.value == "1" else "Off (visible)"
            updated.append(f"**Leaderboard privacy:** {state}")

        if private_results:
            await set_guild_setting(
                interaction.guild.id,
                f"user_private_results:{interaction.user.id}",
                private_results.value,
            )
            state = "On (private)" if private_results.value == "1" else "Off (default)"
            updated.append(f"**Private results:** {state}")

        if not lines and not updated:
            # Show current preferences
            current_tz = await get_user_timezone(interaction.guild.id, interaction.user.id)
            current_platform = await get_user_platform(interaction.guild.id, interaction.user.id)
            quieter_on = await get_quieter_mode(interaction.guild.id)
            from database import get_guild_setting
            dr_val = await get_guild_setting(interaction.guild.id, f"user_daily_reminder:{interaction.user.id}")
            dr_on = dr_val == "1"
            lu_val = await get_guild_setting(interaction.guild.id, f"user_levelup_dm:{interaction.user.id}")
            lu_dm = lu_val == "1"
            an_style = await get_achievement_notify_style(interaction.guild.id, interaction.user.id)
            an_labels = {
                "ephemeral": "Ephemeral 🔔",
                "channel": "Public channel 📣",
                "dm": "DM 📬",
                "off": "Off",
            }
            digest_on = await get_digest_dm(interaction.guild.id, interaction.user.id)
            tf = await get_user_time_format(interaction.guild.id, interaction.user.id)
            inv_val = await get_guild_setting(interaction.guild.id, f"user_investment_dm:{interaction.user.id}")
            inv_on = inv_val == "1"  # default OFF when unset
            th_val = await get_guild_setting(interaction.guild.id, f"user_typo_helper:{interaction.user.id}")
            th_on = th_val != "0"  # default ON when unset
            lb_val = await get_guild_setting(interaction.guild.id, f"user_hide_leaderboards:{interaction.user.id}")
            lb_hidden = lb_val == "1"
            pr_val = await get_guild_setting(interaction.guild.id, f"user_private_results:{interaction.user.id}")
            pr_on = pr_val == "1"
            lines.append(f"**Your timezone:** {current_tz or 'Not set (uses server default)'}")
            lines.append(f"**Trading platform:** {current_platform.upper() if current_platform else 'Not set (defaults to PC)'}")
            lines.append(f"**Daily streak reminder:** {'On 🔔' if dr_on else 'Off'}")
            lines.append(f"**Level-up notification:** {'DM (private) 📬' if lu_dm else 'Public channel'}")
            lines.append(f"**Achievement notifications:** {an_labels.get(an_style, an_style)}")
            lines.append(f"**Daily digest DM:** {'On ☀️' if digest_on else 'Off'}")
            lines.append(f"**Time format:** {'24-hour' if tf == '24' else '12-hour'}")
            lines.append(f"**Investment maturity DM:** {'On 📈' if inv_on else 'Off'}")
            lines.append(f"**Typo helper:** {'On 💡' if th_on else 'Off'}")
            lines.append(f"**Leaderboard privacy:** {'On 🕵️' if lb_hidden else 'Off (name shown)'}")
            lines.append(f"**Private results:** {'On 🔒' if pr_on else 'Off (default)'}")
            if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
                lines.append(f"**Quieter mode:** {'On' if quieter_on else 'Off'}")
            embed = obsidian_embed(
                "⚙️ Preferences",
                "\n".join(lines) or "Set timezone or quieter mode using the options above.",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            )
            from core.help_layout import help_layout_v2_enabled
            from core.preferences_layout import PreferencesLayout

            if help_layout_v2_enabled():
                try:
                    layout = PreferencesLayout(lines=lines)
                    await interaction.followup.send(
                        view=layout,
                        ephemeral=True,
                    )
                    return
                except Exception:
                    pass
            return await interaction.followup.send(
                embed=embed,
                view=_NotificationPrefsView(interaction.user.id, interaction.guild.id),
                ephemeral=True,
            )

        if updated:
            return await interaction.followup.send(
                embed=success_embed("Preferences Updated", "\n".join(updated), client=interaction.client),
                ephemeral=True
            )

        await interaction.followup.send(
            embed=obsidian_embed("⚙️ Preferences", "\n".join(lines), color=discord.Color.orange(), client=interaction.client),
            ephemeral=True
        )

    # ---- Item 61: bulk DM subscribe/unsubscribe -----------------------------------
    # Per-user notification keys controlled by /preferences. Add new keys here when
    # a new user-level toggle is introduced.
    _DM_KEYS: tuple[str, ...] = (
        "user_daily_reminder",
        "user_levelup_dm",
        "user_achievement_notify",
        "user_achievement_notify_style",
        "user_digest_dm",
        "user_investment_dm",
        "user_changelog_dm",
        "user_pet_alerts",
        "user_typo_helper",
    )
    # When the user clicks "Restore Defaults", these are the values we set
    # (matches the comments documented next to /preferences fields above).
    _DM_DEFAULTS: dict[str, str] = {
        "user_daily_reminder": "1",
        "user_levelup_dm": "0",  # public level-up channel by default
        "user_achievement_notify": "1",
        "user_achievement_notify_style": "ephemeral",
        "user_digest_dm": "0",
        "user_investment_dm": "0",
        "user_changelog_dm": "0",
        "user_pet_alerts": "1",
        "user_typo_helper": "1",
    }

    async def _set_all_dm_prefs(guild_id: int, user_id: int, value: str) -> list[str]:
        from database import set_guild_setting as _sgs
        labels: list[str] = []
        for key in _DM_KEYS:
            await _sgs(guild_id, f"{key}:{user_id}", value)
            labels.append(f"`{key.replace('user_', '')}`")
        return labels

    class _NotificationPrefsView(discord.ui.View):
        """Quick toggles for common notification prefs (slash command still works)."""

        def __init__(self, requester_id: int, guild_id: int):
            super().__init__(timeout=180)
            self.requester_id = requester_id
            self.guild_id = guild_id

        async def interaction_check(self, btn_interaction: discord.Interaction) -> bool:
            if btn_interaction.user.id != self.requester_id:
                await btn_interaction.response.send_message(
                    "Only the original user can use these buttons.", ephemeral=True
                )
                return False
            return True

        async def _flip(self, btn_interaction: discord.Interaction, key: str, label: str) -> None:
            from database import get_guild_setting as _ggs, set_guild_setting as _sgs

            cur = await _ggs(self.guild_id, f"{key}:{btn_interaction.user.id}")
            new_val = "0" if cur == "1" else "1"
            await _sgs(self.guild_id, f"{key}:{btn_interaction.user.id}", new_val)
            state = "On" if new_val == "1" else "Off"
            await btn_interaction.response.send_message(
                embed=success_embed(f"{label}: {state}", "Use `/preferences` for all options.", client=btn_interaction.client),
                ephemeral=True,
            )

        @discord.ui.button(label="Daily digest", emoji="☀️", style=discord.ButtonStyle.secondary)
        async def digest_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await self._flip(btn_interaction, "user_digest_dm", "Daily digest DM")

        @discord.ui.button(label="Daily reminder", emoji="🎁", style=discord.ButtonStyle.secondary)
        async def daily_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await self._flip(btn_interaction, "user_daily_reminder", "Daily streak reminder")

        @discord.ui.button(label="Level-up DM", emoji="⭐", style=discord.ButtonStyle.secondary)
        async def levelup_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await self._flip(btn_interaction, "user_levelup_dm", "Level-up DM")

        @discord.ui.button(label="Typo helper", emoji="💡", style=discord.ButtonStyle.secondary)
        async def typo_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await self._flip(btn_interaction, "user_typo_helper", "Typo helper")

    class _RestoreDefaultsView(discord.ui.View):
        def __init__(self, requester_id: int):
            super().__init__(timeout=120)
            self.requester_id = requester_id

        async def interaction_check(self, btn_interaction: discord.Interaction) -> bool:
            if btn_interaction.user.id != self.requester_id:
                await btn_interaction.response.send_message("Only the original user can use this button.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Restore Defaults", emoji="↩", style=discord.ButtonStyle.primary)
        async def restore_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            from database import set_guild_setting as _sgs
            if not btn_interaction.guild:
                return await btn_interaction.response.send_message("Use this in a server.", ephemeral=True)
            for k, v in _DM_DEFAULTS.items():
                await _sgs(btn_interaction.guild.id, f"{k}:{btn_interaction.user.id}", v)
            for c in self.children:
                if isinstance(c, discord.ui.Button):
                    c.disabled = True
            await btn_interaction.response.edit_message(
                embed=success_embed(
                    "Defaults restored",
                    "Notification defaults restored — daily reminders and achievement pings are back on.",
                    client=btn_interaction.client,
                ),
                view=self,
            )

    pref_unsub = group.command(
        name="unsubscribe_all",
        description="Turn OFF every DM notification at once.",
    ) if group else bot.tree.command(
        name="unsubscribe_all",
        description="Turn OFF every DM notification at once.",
    )

    @pref_unsub
    async def preferences_unsubscribe_all(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used inside a server.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        flipped = await _set_all_dm_prefs(interaction.guild.id, interaction.user.id, "0")
        body = (
            "All bot DM notifications turned **off** for you in this server:\n"
            + ", ".join(flipped)
            + "\n\nClick **Restore Defaults** to bring back the helpful ones."
        )
        await interaction.followup.send(
            embed=obsidian_embed(
                "🔕 Unsubscribed from all bot DMs",
                body,
                color=EMBED_COLORS["general"],
                client=interaction.client,
            ),
            view=_RestoreDefaultsView(interaction.user.id),
            ephemeral=True,
        )

    pref_sub = group.command(
        name="subscribe_all",
        description="Turn ON every DM notification at once.",
    ) if group else bot.tree.command(
        name="subscribe_all",
        description="Turn ON every DM notification at once.",
    )

    @pref_sub
    async def preferences_subscribe_all(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used inside a server.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        flipped = await _set_all_dm_prefs(interaction.guild.id, interaction.user.id, "1")
        await interaction.followup.send(
            embed=success_embed(
                "Subscribed to all bot DMs",
                "Every DM notification is now **on**: " + ", ".join(flipped) +
                "\n\nUse `/general unsubscribe_all` to turn them off again.",
                client=interaction.client,
            ),
            ephemeral=True,
        )
