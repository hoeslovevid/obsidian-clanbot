"""User and guild preferences (timezone, quieter mode)."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, success_embed, is_mod, EMBED_COLORS
from database import get_user_timezone, set_user_timezone, get_user_platform, set_user_platform, get_quieter_mode, set_quieter_mode

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
        achievement_notify="Show a private notification when you unlock an achievement",
        investment_dm="Get a DM when your investment matures and is ready to collect",
        typo_helper="Reply with a slash-command suggestion when you mis-type one in chat",
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
    @app_commands.choices(investment_dm=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    @app_commands.choices(typo_helper=[
        app_commands.Choice(name="On", value="1"),
        app_commands.Choice(name="Off", value="0"),
    ])
    async def preferences(
        interaction: discord.Interaction,
        timezone: Optional[app_commands.Choice[str]] = None,
        platform: Optional[app_commands.Choice[str]] = None,
        quieter: Optional[app_commands.Choice[str]] = None,
        daily_reminder: Optional[app_commands.Choice[str]] = None,
        levelup_dm: Optional[app_commands.Choice[str]] = None,
        achievement_notify: Optional[app_commands.Choice[str]] = None,
        investment_dm: Optional[app_commands.Choice[str]] = None,
        typo_helper: Optional[app_commands.Choice[str]] = None,
    ):
        """Set timezone or quieter mode."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
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

        if achievement_notify:
            from database import set_guild_setting
            await set_guild_setting(interaction.guild.id, f"user_achievement_notify:{interaction.user.id}", achievement_notify.value)
            state = "On" if achievement_notify.value == "1" else "Off"
            updated.append(f"**Achievement notifications:** {state}")

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
            an_val = await get_guild_setting(interaction.guild.id, f"user_achievement_notify:{interaction.user.id}")
            an_on = an_val != "0"  # default ON when unset
            inv_val = await get_guild_setting(interaction.guild.id, f"user_investment_dm:{interaction.user.id}")
            inv_on = inv_val == "1"  # default OFF when unset
            th_val = await get_guild_setting(interaction.guild.id, f"user_typo_helper:{interaction.user.id}")
            th_on = th_val != "0"  # default ON when unset
            lines.append(f"**Your timezone:** {current_tz or 'Not set (uses server default)'}")
            lines.append(f"**Trading platform:** {current_platform.upper() if current_platform else 'Not set (defaults to PC)'}")
            lines.append(f"**Daily streak reminder:** {'On 🔔' if dr_on else 'Off'}")
            lines.append(f"**Level-up notification:** {'DM (private) 📬' if lu_dm else 'Public channel'}")
            lines.append(f"**Achievement notifications:** {'On 🏆' if an_on else 'Off'}")
            lines.append(f"**Investment maturity DM:** {'On 📈' if inv_on else 'Off'}")
            lines.append(f"**Typo helper:** {'On 💡' if th_on else 'Off'}")
            if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
                lines.append(f"**Quieter mode:** {'On' if quieter_on else 'Off'}")
            embed = obsidian_embed(
                "⚙️ Preferences",
                "\n".join(lines) or "Set timezone or quieter mode using the options above.",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

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
                embed=obsidian_embed("❌ Invalid Context", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
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
                embed=obsidian_embed("❌ Invalid Context", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
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
