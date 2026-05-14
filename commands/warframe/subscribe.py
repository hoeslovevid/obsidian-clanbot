"""Per-user Warframe ping opt-in (Item 2).

Stores opt-in state in ``guild_settings`` under ``wfsub:{category}:{user_id}``.
Notification senders use :func:`core.utils.build_wf_subscriber_ping` to mention
either an opt-in role (preferred — cheaper for Discord's 100-mention cap) or
the opted-in users themselves.
"""
import discord
from discord import app_commands

from core.utils import (
    obsidian_embed,
    success_embed,
    error_embed,
    WF_SUB_CATEGORIES,
    get_wf_subscribers,
)
from database import set_guild_setting, delete_guild_setting, get_guild_setting


_CATEGORY_CHOICES = [
    app_commands.Choice(name="Baro Ki'Teer", value="baro"),
    app_commands.Choice(name="Archon Hunt", value="archon"),
    app_commands.Choice(name="Open-world cycles (Cetus / Fortuna / Deimos)", value="cycles"),
    app_commands.Choice(name="World alerts", value="alerts"),
    app_commands.Choice(name="Invasions", value="invasions"),
    app_commands.Choice(name="Devstream", value="devstream"),
]


def setup(bot, group=None):
    """Register the ``/warframe subscribe`` command."""
    if group is None:
        # Top-level fallback — keeps the file usable if loader pattern shifts.
        cmd_decorator = bot.tree.command(
            name="subscribe",
            description="Subscribe to per-user Warframe notification pings.",
        )
    else:
        cmd_decorator = group.command(
            name="subscribe",
            description="Subscribe / unsubscribe yourself from Warframe notification pings.",
        )

    @cmd_decorator
    @app_commands.describe(
        category="Which Warframe notification stream to (un)subscribe to",
        state="Turn this subscription on or off",
    )
    @app_commands.choices(category=_CATEGORY_CHOICES)
    @app_commands.choices(state=[
        app_commands.Choice(name="On — ping me when this drops", value="on"),
        app_commands.Choice(name="Off — stop pinging me", value="off"),
    ])
    async def subscribe(
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        state: app_commands.Choice[str],
    ):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Invalid Context",
                    "This command can only be used in a server.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        cat = category.value
        if cat not in WF_SUB_CATEGORIES:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Unknown category",
                    f"`{cat}` is not a known Warframe subscription category.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        key = f"wfsub:{cat}:{interaction.user.id}"
        if state.value == "on":
            await set_guild_setting(interaction.guild.id, key, "1")
        else:
            await delete_guild_setting(interaction.guild.id, key)

        # Tell the user how many others share this subscription so the value of
        # opting in / out is concrete.
        subs = await get_wf_subscribers(interaction.guild.id, cat)
        role_id_raw = await get_guild_setting(interaction.guild.id, f"wfsub_role:{cat}")
        role_note = ""
        if role_id_raw and str(role_id_raw).isdigit():
            role = interaction.guild.get_role(int(role_id_raw))
            if role:
                role_note = (
                    f"\n\n_This guild also pings {role.mention} for {category.name} — "
                    "asking a mod to add you to that role gives you the same notifications._"
                )

        if state.value == "on":
            embed = success_embed(
                f"Subscribed to {category.name}",
                f"You'll be pinged the next time **{category.name}** drops.\n\n"
                f"Currently **{len(subs)}** member(s) are subscribed to this stream.{role_note}\n\n"
                f"Use `/warframe subscribe category:{cat} state:Off` to stop.",
                client=interaction.client,
            )
        else:
            embed = obsidian_embed(
                f"🔕 Unsubscribed from {category.name}",
                f"You will no longer be pinged for **{category.name}**.\n\n"
                f"**{len(subs)}** member(s) remain subscribed.{role_note}",
                category="warning",
                client=interaction.client,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
