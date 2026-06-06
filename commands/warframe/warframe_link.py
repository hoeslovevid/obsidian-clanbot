"""Link Steam account for Warframe in-game achievement roles (playtime-based)."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed
from database import link_steam_account, unlink_steam_account, get_linked_steam_id, update_steam_playtime
from api.warframe_api import resolve_steam_id, fetch_steam_warframe_playtime


def setup(bot, group=None):
    """Register the warframe_link command."""
    command_decorator = (
        group.command(
            name="warframe_link",
            description="Link your Steam account for Warframe playtime roles.",
        )
        if group
        else bot.tree.command(
            name="warframe_link",
            description="Link your Steam account for Warframe playtime roles.",
        )
    )

    @command_decorator
    @app_commands.describe(
        steam="Your Steam profile URL or Steam ID (e.g. https://steamcommunity.com/id/username)",
        in_game_name="Your Warframe in-game name (your server nickname will be set to this)",
        action="Link or unlink your Steam account"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Link", value="link"),
        app_commands.Choice(name="Unlink", value="unlink"),
    ])
    async def warframe_link(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        steam: Optional[str] = None,
        in_game_name: Optional[str] = None,
    ):
        """Link or unlink Steam account for Warframe playtime tracking."""
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

        if action.value == "unlink":
            await unlink_steam_account(interaction.guild.id, interaction.user.id)
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Steam Account Unlinked",
                    "Your Steam account has been unlinked. You will no longer receive Warframe playtime roles.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # Link
        if not steam or not steam.strip():
            if in_game_name and in_game_name.strip():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Steam Required",
                        "To update your in-game name, also provide your Steam URL. Or use action:Unlink first.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            current = await get_linked_steam_id(interaction.guild.id, interaction.user.id)
            if current:
                hours = await fetch_steam_warframe_playtime(current)
                playtime_text = f"**Playtime:** {hours:,} hours" if hours is not None else "**Playtime:** Private (set Game details to Public)"
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "🔗 Steam Linked",
                        f"Your Steam account is linked.\n\n{playtime_text}\n\n"
                        "Provide a new Steam URL to change your link.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Missing Steam Info",
                    "Please provide your Steam profile URL or Steam ID and your Warframe in-game name.\n\n"
                    "Examples:\n"
                    "• `https://steamcommunity.com/id/yourname`\n"
                    "• `https://steamcommunity.com/profiles/76561198000000000`\n"
                    "• Your Steam ID (17 digits)\n\n"
                    "**Note:** Set your Steam profile and **Game details** to Public for playtime to be tracked.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if not in_game_name or not in_game_name.strip():
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ In-Game Name Required",
                    "Please provide your Warframe in-game name. Your server nickname will be set to match it.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        ign = in_game_name.strip()[:32]  # Discord nickname limit

        steam_id = await resolve_steam_id(steam.strip())
        if not steam_id:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Could Not Resolve Steam ID",
                    "Could not find your Steam account. Check that:\n"
                    "• The URL or ID is correct\n"
                    "• Your profile is set to Public\n\n"
                    "Get your Steam ID: https://steamid.io/",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await link_steam_account(interaction.guild.id, interaction.user.id, steam_id, warframe_ign=ign)

        from database import get_guild_setting, now_utc
        import aiosqlite
        from core.config import DB_PATH
        verify_mode = await get_guild_setting(interaction.guild.id, "ign_verify_mode") or "auto"
        status = "verified" if verify_mode.strip().lower() == "auto" else "pending"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO ign_verifications
                (guild_id, user_id, ign, status, verified_by, verified_at, created_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    interaction.guild.id,
                    interaction.user.id,
                    ign,
                    status,
                    interaction.user.id if status == "verified" else None,
                    now_utc().isoformat() if status == "verified" else None,
                    now_utc().isoformat(),
                ),
            )
            await db.commit()

        # Set server nickname to in-game name
        nick_set = False
        if isinstance(interaction.user, discord.Member):
            if interaction.guild.me.guild_permissions.manage_nicknames:
                try:
                    await interaction.user.edit(nick=ign, reason="Warframe account link - set to IGN")
                    nick_set = True
                except discord.Forbidden:
                    pass  # User may have higher role than bot
                except discord.HTTPException:
                    pass  # Nickname invalid or other API error

        # Verify we can fetch playtime and store it
        hours = await fetch_steam_warframe_playtime(steam_id)
        if hours is not None:
            await update_steam_playtime(interaction.guild.id, interaction.user.id, hours)
            # Immediately check and assign any roles they qualify for
            from database import (
                get_warframe_achievement_roles,
                has_warframe_achievement_unlock,
                record_warframe_achievement_unlock,
            )
            role_configs = await get_warframe_achievement_roles(interaction.guild.id)
            for ach_type, threshold, role_id in role_configs:
                if ach_type != "playtime" or hours < threshold:
                    continue
                if await has_warframe_achievement_unlock(interaction.guild.id, interaction.user.id, ach_type, threshold):
                    continue
                role = interaction.guild.get_role(role_id)
                if role and role not in interaction.user.roles:
                    if interaction.guild.me.guild_permissions.manage_roles and interaction.guild.me.top_role > role:
                        try:
                            await interaction.user.add_roles(role, reason=f"Warframe playtime: {hours:,}h")
                            await record_warframe_achievement_unlock(interaction.guild.id, interaction.user.id, ach_type, threshold)
                        except discord.Forbidden:
                            pass
        if hours is None:
            nick_note = f"Your nickname has been set to **{ign}**.\n\n" if nick_set else ""
            badge = "✅ IGN verified." if status == "verified" else "⏳ IGN pending mod verification."
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "⚠️ Linked (Playtime Private)",
                    f"{nick_note}{badge}\n"
                    "Your Steam account is linked, but playtime could not be fetched.\n\n"
                    "**Set your Game details to Public:**\n"
                    "Steam → Profile → Edit Profile → Privacy Settings → Game details: **Public**\n\n"
                    "Roles will be assigned once your playtime is visible.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        nick_msg = f"Your nickname has been set to **{ign}**.\n\n" if nick_set else ""
        badge = "✅ IGN verified on your profile." if status == "verified" else "⏳ IGN pending mod verification."
        return await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Warframe Account Linked",
                f"Your Steam account is linked. Warframe playtime: **{hours:,} hours**.\n\n"
                f"{nick_msg}{badge}\n"
                "You'll receive roles automatically as you hit playtime milestones (if configured by moderators).",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
