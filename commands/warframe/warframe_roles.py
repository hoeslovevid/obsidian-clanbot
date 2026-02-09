"""Configure Warframe in-game achievement roles (playtime-based). Moderators only."""
import discord  # type: ignore
from discord import app_commands  # type: ignore
from typing import Optional

from utils import obsidian_embed, is_mod
from database import (
    add_warframe_achievement_role,
    remove_warframe_achievement_role,
    get_warframe_achievement_roles,
)

# Supported achievement types and display names
ACHIEVEMENT_TYPES = {
    "playtime": ("Playtime (hours)", "Hours played in Warframe (Steam)"),
}


def setup(bot, group=None):
    """Register the warframe_roles command."""
    command_decorator = (
        group.command(
            name="warframe_roles",
            description="Configure roles for Warframe in-game achievements like playtime (moderators only).",
        )
        if group
        else bot.tree.command(
            name="warframe_roles",
            description="Configure roles for Warframe in-game achievements like playtime (moderators only).",
        )
    )

    @command_decorator
    @app_commands.describe(
        action="What to do",
        achievement_type="Type of achievement (playtime = hours in Warframe)",
        hours="Hours required (for playtime type)",
        role="Role to assign when achieved"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    @app_commands.choices(achievement_type=[
        app_commands.Choice(name="Playtime (hours)", value="playtime"),
    ])
    async def warframe_roles(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        achievement_type: Optional[app_commands.Choice[str]] = None,
        hours: Optional[int] = None,
        role: Optional[discord.Role] = None,
    ):
        """Configure Warframe achievement roles."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can configure Warframe achievement roles.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        act = action.value
        ach_type = achievement_type.value if achievement_type else "playtime"

        if act == "list":
            roles = await get_warframe_achievement_roles(interaction.guild.id)
            if not roles:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Warframe Achievement Roles",
                        "No roles configured yet.\n\n"
                        "Use **Add** to assign a role when users reach a playtime milestone. "
                        "Users must link their Steam account with `/warframe_link` first.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            lines = []
            for atype, threshold, role_id in roles:
                r = interaction.guild.get_role(role_id)
                label = ACHIEVEMENT_TYPES.get(atype, (atype, ""))[0]
                lines.append(f"• **{label}** ≥ {threshold:,} → {r.mention if r else f'Role {role_id}'}")
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Warframe Achievement Roles",
                    "\n".join(lines) + "\n\n*Users need `/warframe_link` to receive roles.*",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if act == "add":
            if not hours or hours < 1:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Hours",
                        "Please specify a positive number of hours (e.g. 100, 500, 1000).",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            if not role:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Role",
                        "Please specify the role to assign.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            if not interaction.guild.me.guild_permissions.manage_roles:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Permission Error",
                        "I need the Manage Roles permission to assign roles.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            if interaction.guild.me.top_role <= role:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Role Hierarchy",
                        "My role must be higher than the role I'm assigning. Move my role above it in Server Settings.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            await add_warframe_achievement_role(
                interaction.guild.id, ach_type, hours, role.id
            )
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Role Added",
                    f"Users with **≥{hours:,} hours** of Warframe playtime will receive {role.mention}.\n\n"
                    "They must link Steam with `/warframe_link`. Roles are checked periodically.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if act == "remove":
            if not hours or hours < 1:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Hours",
                        "Please specify the hours threshold to remove (e.g. 500).",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            await remove_warframe_achievement_role(
                interaction.guild.id, ach_type, hours
            )
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Role Removed",
                    f"Removed the role for ≥{hours:,} hours playtime.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )  # type: ignore[awaitable]
