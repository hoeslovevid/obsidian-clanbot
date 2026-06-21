"""Twitch integration commands."""
from __future__ import annotations

from typing import Optional

import aiosqlite  # type: ignore
import discord
from discord import app_commands

from core.twitch_api import (
    check_twitch_stream,
    fetch_twitch_streams_batch,
    format_twitch_diagnostics,
    get_guild_twitch_settings,
    get_twitch_access_token,
    guild_twitch_setup_status,
    resolve_twitch_user,
    twitch_credentials_configured,
)
from core.utils import is_mod, obsidian_embed
from database import DB_PATH

# Re-export for callers that import from this module.
__all__ = ["get_twitch_access_token", "check_twitch_stream", "setup"]


def setup(bot, group=None):
    """Register Twitch commands."""

    def _mod_only(interaction: discord.Interaction) -> bool:
        return isinstance(interaction.user, discord.Member) and is_mod(interaction.user)

    command_decorator = (
        group.command(
            name="twitch_setup",
            description="Configure Twitch stream notifications (moderators only).",
        )
        if group
        else bot.tree.command(
            name="twitch_setup",
            description="Configure Twitch stream notifications (moderators only).",
        )
    )

    @command_decorator
    @app_commands.describe(
        channel="Channel to send notifications to",
        ping_role="Role to ping when streamers go live (optional)",
        enabled="Enable or disable notifications",
    )
    async def twitch_setup(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        ping_role: Optional[discord.Role] = None,
        enabled: bool = True,
    ):
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
        if not _mod_only(interaction):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        if not twitch_credentials_configured():
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "⚠️ Twitch API Not Configured",
                    "Saved your channel, but the bot host is missing `TWITCH_CLIENT_ID` and "
                    "`TWITCH_CLIENT_SECRET`. Set those on Railway, redeploy, then add streamers.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO twitch_settings (guild_id, channel_id, enabled, ping_role_id)
                VALUES (?, ?, ?, ?)
                """,
                (interaction.guild.id, channel.id, 1 if enabled else 0, ping_role.id if ping_role else None),
            )
            await db.commit()

        ping_text = (
            f"**Ping Role:** {ping_role.mention}"
            if ping_role
            else "**Ping Role:** None (no role will be pinged)"
        )
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Twitch Notifications Configured",
                f"**Channel:** {channel.mention}\n{ping_text}\n**Status:** {'Enabled' if enabled else 'Disabled'}\n\n"
                "Use `/community twitch_add` to add streamers to monitor.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    command_decorator = (
        group.command(
            name="twitch_add",
            description="Add a Twitch streamer to monitor (moderators only).",
        )
        if group
        else bot.tree.command(
            name="twitch_add",
            description="Add a Twitch streamer to monitor (moderators only).",
        )
    )

    @command_decorator
    @app_commands.describe(streamer_name="Twitch login (from twitch.tv/username)")
    async def twitch_add(interaction: discord.Interaction, streamer_name: str):
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
        if not _mod_only(interaction):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        if not twitch_credentials_configured():
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Twitch API Not Configured",
                    "Set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` on the bot host before adding streamers.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        token = await get_twitch_access_token()
        if not token:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Twitch API Error",
                    "Could not obtain a Twitch access token. Check bot logs and API credentials.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        user = await resolve_twitch_user(streamer_name, token)
        if not user:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Streamer Not Found",
                    f"No Twitch user **`{streamer_name.strip()}`**.\n"
                    "Use the login from the channel URL (e.g. `twitch.tv/shroud` → `shroud`), not display name.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        login = str(user.get("login", streamer_name)).lower()
        display = str(user.get("display_name", login))

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT 1 FROM twitch_streamers WHERE guild_id=? AND streamer_name=?",
                (interaction.guild.id, login),
            )
            if await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Added",
                        f"**{display}** (`{login}`) is already being monitored.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )

            live_now = await check_twitch_stream(login, token)
            initial_status = 1 if live_now else 0
            initial_stream_id = str(live_now.get("id") or "") if live_now else None
            await db.execute(
                """
                INSERT INTO twitch_streamers (guild_id, streamer_name, twitch_user_id, last_live_status, last_stream_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (interaction.guild.id, login, str(user.get("id", "")), initial_status, initial_stream_id),
            )
            await db.commit()

        ready, setup_reason = await guild_twitch_setup_status(interaction.guild.id)
        lines = [f"**{display}** (`{login}`) added to the watch list."]
        if live_now:
            lines.append(
                "-# Currently **live** — you'll be pinged when they go live **next** (not for this session)."
            )
        if not ready:
            lines.append(f"\n⚠️ **Alerts not active:** {setup_reason}")
        else:
            settings = await get_guild_twitch_settings(interaction.guild.id)
            ch = interaction.guild.get_channel(int(settings["channel_id"])) if settings else None
            if isinstance(ch, discord.TextChannel):
                lines.append(f"\nNotifications will post in {ch.mention} (checked every ~3 minutes).")

        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Streamer Added",
                "\n".join(lines),
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    command_decorator = (
        group.command(
            name="twitch_remove",
            description="Remove a Twitch streamer from monitoring (moderators only).",
        )
        if group
        else bot.tree.command(
            name="twitch_remove",
            description="Remove a Twitch streamer from monitoring (moderators only).",
        )
    )

    @command_decorator
    @app_commands.describe(streamer_name="Twitch username")
    async def twitch_remove(interaction: discord.Interaction, streamer_name: str):
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
        if not _mod_only(interaction):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        login = streamer_name.strip().lower()

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "DELETE FROM twitch_streamers WHERE guild_id=? AND streamer_name=?",
                (interaction.guild.id, login),
            )
            await db.commit()
            if cur.rowcount == 0:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Not Found",
                        f"`{login}` is not on the watch list.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )

        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Streamer Removed",
                f"`{login}` removed from the watch list.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    command_decorator = (
        group.command(
            name="twitch_list",
            description="List monitored Twitch streamers (live status from Twitch API).",
        )
        if group
        else bot.tree.command(
            name="twitch_list",
            description="List monitored Twitch streamers (live status from Twitch API).",
        )
    )

    @command_decorator
    @app_commands.describe(
        diagnostics="Show API/setup diagnostics (moderators only)",
        force_check="Run an immediate live check and post alerts if someone just went live (moderators only)",
    )
    async def twitch_list(
        interaction: discord.Interaction,
        diagnostics: bool = False,
        force_check: bool = False,
    ):
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
        if (diagnostics or force_check) and not _mod_only(interaction):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Diagnostics and force check are moderator-only.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT streamer_name, last_live_status, last_notified_at
                FROM twitch_streamers WHERE guild_id=? ORDER BY streamer_name
                """,
                (interaction.guild.id,),
            )
            streamers = await cur.fetchall()

        if force_check:
            from tasks.integration_loops import run_twitch_live_cycle

            sent = await run_twitch_live_cycle(interaction.client, guild_id=interaction.guild.id)
            if sent < 0:
                force_line = "⚠️ Force check ran but the bot lacks **Send Messages** / **Embed Links** in the notify channel."
            elif sent > 0:
                force_line = f"✅ Force check posted **{sent}** live alert(s)."
            else:
                force_line = "✅ Force check complete — no new go-live transitions."
        else:
            force_line = ""

        if not streamers:
            body = "No streamers on the watch list. Mods: `/community twitch_add`."
            if diagnostics:
                ready, setup_reason = await guild_twitch_setup_status(interaction.guild.id)
                body = f"{format_twitch_diagnostics()}\n**Setup:** {setup_reason}"
            if force_line:
                body = f"{force_line}\n\n{body}"
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📺 Twitch Watch List",
                    body,
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        logins = [str(name).lower() for name, _, _ in streamers]
        user_ids = []
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT twitch_user_id FROM twitch_streamers WHERE guild_id=?",
                (interaction.guild.id,),
            )
            user_ids = [str(r[0]) for r in await cur.fetchall() if r and r[0]]
        live_map: dict[str, dict] = {}
        if twitch_credentials_configured():
            token = await get_twitch_access_token()
            if token:
                live_map = await fetch_twitch_streams_batch(logins, token, user_ids=user_ids)

        lines: list[str] = []
        for name, db_status, last_notified in streamers:
            login = str(name).lower()
            if login in live_map:
                stream = live_map[login]
                game = stream.get("game_name", "?")
                viewers = stream.get("viewer_count", 0)
                lines.append(f"• **{login}** 🔴 Live — {game} ({viewers:,} viewers)")
            else:
                suffix = ""
                if db_status and not live_map:
                    suffix = " _(DB said live; API unreachable)_"
                elif db_status:
                    suffix = " _(DB out of sync — next poll will fix)_"
                lines.append(f"• **{login}** ⚫ Offline{suffix}")
            if diagnostics and last_notified:
                lines.append(f"  -# Last alert: {str(last_notified)[:19]} UTC")

        body = "\n".join(lines)
        if diagnostics:
            ready, setup_reason = await guild_twitch_setup_status(interaction.guild.id)
            settings = await get_guild_twitch_settings(interaction.guild.id)
            ch_note = ""
            if settings and settings.get("channel_id"):
                ch = interaction.guild.get_channel(int(settings["channel_id"]))
                if isinstance(ch, discord.TextChannel):
                    me = interaction.guild.me
                    if me:
                        perms = ch.permissions_for(me)
                        perm_ok = perms.send_messages and perms.embed_links
                        ch_note = f"\n**Channel:** {ch.mention} ({'OK' if perm_ok else 'missing send/embed perms'})"
            body = (
                f"{format_twitch_diagnostics()}\n**Setup:** {setup_reason}{ch_note}\n\n{body}"
            )
        if force_line:
            body = f"{force_line}\n\n{body}"

        await interaction.followup.send(
            embed=obsidian_embed(
                "📺 Twitch Watch List",
                body,
                color=discord.Color.purple(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
