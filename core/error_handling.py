"""Structured slash-command error handling, mod digests, and diagnostics."""
from __future__ import annotations

import asyncio
import logging
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import discord
from discord import app_commands

from core.config import GUILD_ID
from core.utils import obsidian_embed
from database import get_log_channel_id, now_utc

logger = logging.getLogger(__name__)

RECENT_ERRORS: deque[dict[str, Any]] = deque(maxlen=20)
_resync_scheduled = False

# exc type name -> (user_message, action_hint, error_code)
KNOWN_EXCEPTIONS: dict[str, tuple[str, Optional[str], str]] = {
    "IntegrityError": (
        "That action conflicted with existing data.",
        "Wait a moment and try again.",
        "DB_UNIQUE",
    ),
    "OperationalError": (
        "The database is busy right now.",
        "Try again in a few seconds.",
        "DB_BUSY",
    ),
    "UnboundLocalError": (
        "Something went wrong internally.",
        "Tell staff if this keeps happening — include the error code below.",
        "INTERNAL",
    ),
    "AttributeError": (
        "Something went wrong internally.",
        "Try again or ask staff if it persists.",
        "INTERNAL",
    ),
    "TimeoutError": (
        "The request timed out.",
        "Try again in a moment.",
        "TIMEOUT",
    ),
    "ConnectionError": (
        "Could not reach an external service.",
        "Try again shortly.",
        "NETWORK",
    ),
    "NotFound": (
        "That resource no longer exists or expired.",
        "Run the command again from scratch.",
        "NOT_FOUND",
    ),
    "ValueError": (
        "Invalid input for this command.",
        "Check your options and try again.",
        "BAD_INPUT",
    ),
}


def classify_exception(exc: BaseException) -> tuple[str, Optional[str], str]:
    """Map an exception to a user-facing message, hint, and short error code."""
    name = type(exc).__name__
    if name in KNOWN_EXCEPTIONS:
        return KNOWN_EXCEPTIONS[name]

    msg = str(exc).lower()
    if "unique constraint" in msg or "integrity" in msg:
        return KNOWN_EXCEPTIONS["IntegrityError"]
    if "database is locked" in msg or "database locked" in msg:
        return KNOWN_EXCEPTIONS["OperationalError"]
    if "timeout" in msg:
        return KNOWN_EXCEPTIONS["TimeoutError"]

    return (
        "Something went wrong. Please try again later.",
        "If it keeps happening, tell staff and mention the error code below.",
        "UNKNOWN",
    )


def record_error(
    *,
    error_code: str,
    command_name: Optional[str],
    guild_id: Optional[int],
    exc: BaseException,
    user_message: str,
) -> None:
    RECENT_ERRORS.append(
        {
            "at": now_utc().isoformat(),
            "code": error_code,
            "command": command_name,
            "guild_id": guild_id,
            "exc_type": type(exc).__name__,
            "exc_msg": str(exc)[:200],
            "user_message": user_message,
        }
    )


async def send_error_reply(
    interaction: discord.Interaction,
    message: str,
    *,
    ephemeral: bool = True,
    action_hint: Optional[str] = None,
    error_code: Optional[str] = None,
) -> None:
    """Send a consistent error embed, using followup if the response was already sent."""
    from core.utils import error_embed
    from core.embed_links import add_link_row, help_link_buttons

    ticket_hint = None
    if error_code:
        ticket_hint = f"Open **`/ticket`** and mention code **`{error_code}`** if you need staff help."
    merged_hint = action_hint
    if ticket_hint:
        merged_hint = f"{action_hint}\n\n{ticket_hint}" if action_hint else ticket_hint

    emb = error_embed("Error", message, action_hint=merged_hint, client=interaction.client, error_code=error_code)
    view = None
    if error_code:
        view = discord.ui.View(timeout=120)

        class _CopyErrorCodeButton(discord.ui.Button):
            def __init__(self, code: str):
                super().__init__(label=f"Copy code: {code}", style=discord.ButtonStyle.secondary, emoji="📋")
                self._code = code

            async def callback(self, btn_interaction: discord.Interaction):
                await btn_interaction.response.send_message(
                    f"Copy for **`/ticket`**: `{self._code}`",
                    ephemeral=True,
                )

        view.add_item(_CopyErrorCodeButton(error_code))
        add_link_row(view, help_link_buttons())
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=emb, view=view, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=emb, view=view, ephemeral=ephemeral)
    except Exception:
        pass


async def notify_mods_error_digest(
    bot: discord.Client,
    interaction: discord.Interaction,
    *,
    error_code: str,
    user_message: str,
    exc: BaseException,
) -> None:
    """Post a compact error digest to the guild bot-error log channel (best-effort)."""
    if not interaction.guild:
        return

    channel_id = await get_log_channel_id(interaction.guild.id, "bot_error")
    if not channel_id:
        channel_id = await get_log_channel_id(interaction.guild.id, "audit")
    if not channel_id:
        return

    channel = interaction.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    cmd_name = None
    if interaction.command is not None:
        cmd_name = getattr(interaction.command, "qualified_name", None) or getattr(
            interaction.command, "name", None
        )

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    tb_short = tb[-900:] if len(tb) > 900 else tb

    embed = obsidian_embed(
        f"⚠️ Command error · `{error_code}`",
        user_message,
        color=discord.Color.orange(),
        client=bot,
    )
    embed.add_field(name="Command", value=f"`/{cmd_name or 'unknown'}`", inline=True)
    embed.add_field(
        name="User",
        value=interaction.user.mention if interaction.user else "Unknown",
        inline=True,
    )
    embed.add_field(name="Exception", value=f"`{type(exc).__name__}`", inline=True)
    embed.add_field(name="Traceback (tail)", value=f"```\n{tb_short}\n```", inline=False)

    try:
        await channel.send(embed=embed)
    except Exception as post_err:
        logger.debug(f"[errors] Failed to post mod digest: {post_err}")


async def schedule_command_resync(bot: discord.Client) -> None:
    """Background guild/global command sync after signature mismatch (debounced)."""
    global _resync_scheduled
    if _resync_scheduled:
        return
    _resync_scheduled = True

    async def _run() -> None:
        global _resync_scheduled
        await asyncio.sleep(3)
        try:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                synced = await bot.tree.sync(guild=guild)
                bot._command_sync_guild_id = GUILD_ID
                logger.info(f"[errors] Background resync: {len(synced)} commands to guild {GUILD_ID}")
            else:
                synced = await bot.tree.sync()
                bot._command_sync_guild_id = None
                logger.info(f"[errors] Background resync: {len(synced)} commands globally")
            from core.command_tree_stats import collect_command_tree_stats

            bot._command_tree_stats = collect_command_tree_stats(bot)
            setattr(bot, "_last_command_sync", now_utc())
        except Exception as sync_err:
            logger.warning(f"[errors] Background command resync failed: {sync_err}")
        finally:
            _resync_scheduled = False

    asyncio.create_task(_run())


async def handle_app_command_error(
    bot: discord.Client,
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
    *,
    find_similar_commands: Callable[[str, list[str], int], list[str]],
) -> None:
    """Central handler for slash command errors."""
    error_type_name = type(error).__name__

    if error_type_name == "CommandNotFound":
        command_name = str(error).split("'")[1] if "'" in str(error) else "unknown"
        moved_commands = {"sync_commands": "general sync_commands"}
        if command_name in moved_commands:
            logger.debug(f"[commands] CommandNotFound for '{command_name}' - Discord cache will update")
            return
        try:
            all_names: list[str] = []
            iclient = interaction.client
            if not isinstance(iclient, discord.Client):
                raise TypeError("expected discord.Client")
            for cmd in iclient.tree.get_commands(guild=interaction.guild):
                if isinstance(cmd, app_commands.Group):
                    all_names.append(cmd.name)
                    for sub in cmd.commands:
                        if isinstance(sub, app_commands.Group):
                            for g in sub.commands:
                                all_names.append(f"{cmd.name} {sub.name} {g.name}")
                        else:
                            all_names.append(f"{cmd.name} {sub.name}")
                else:
                    all_names.append(cmd.name)
            similar = find_similar_commands(command_name, all_names)
            if similar:
                from core.command_mentions import command_mention

                chips = " or ".join(command_mention(name) for name in similar[:3])
                hint = f" Did you mean: {chips}?"
                await send_error_reply(interaction, f"Unknown command `{command_name}`.{hint}")
                return
        except Exception:
            pass
        logger.debug(f"[commands] CommandNotFound: {error}")
        return

    if error_type_name == "CommandSignatureMismatch":
        logger.warning("[commands] CommandSignatureMismatch - Discord cache out of sync")
        await send_error_reply(
            interaction,
            "This command was updated recently and Discord hasn't refreshed yet.",
            action_hint="Try again in ~30 seconds. Staff can run `/admin health` to verify sync.",
            error_code="SYNC_MISMATCH",
        )
        await schedule_command_resync(bot)
        return

    if error_type_name == "CommandOnCooldown":
        retry_after = getattr(error, "retry_after", None) or 0
        if retry_after >= 3600:
            h = int(retry_after // 3600)
            m = int((retry_after % 3600) // 60)
            wait_str = f"**{h}h {m}m**" if m else f"**{h}h**"
        elif retry_after >= 60:
            m = int(retry_after // 60)
            s = int(retry_after % 60)
            wait_str = f"**{m}m {s}s**" if s else f"**{m}m**"
        elif retry_after >= 1:
            wait_str = f"**{int(retry_after)}s**"
        else:
            wait_str = "**a moment**"
        cmd_name = getattr(interaction.command, "qualified_name", None)
        cmd_str = f"`/{cmd_name}` " if cmd_name else "This command "
        ready_ts = int(now_utc().timestamp() + retry_after)
        msg = (
            f"⏳ Slow down! {cmd_str}can be used again in {wait_str}.\n"
            f"Ready <t:{ready_ts}:R> (<t:{ready_ts}:t>)."
        )
        await send_error_reply(
            interaction, msg, action_hint="Use /help to explore other commands while you wait."
        )
        return

    if error_type_name in ("CheckFailure", "MissingRole", "MissingAnyRole"):
        await send_error_reply(
            interaction,
            "You don't have permission to use this command.",
            action_hint="Ask an administrator if you need access.",
        )
        return

    if error_type_name == "MissingPermissions":
        perms = getattr(error, "missing_permissions", None) or []
        if perms:
            names = [str(p).replace("_", " ").title() for p in perms]
            await send_error_reply(
                interaction,
                f"You need: **{', '.join(names)}**. Ask an admin to grant them.",
            )
        else:
            await send_error_reply(interaction, "You don't have permission to use this command.")
        return

    if error_type_name in ("Forbidden", "HTTPException"):
        err_msg = str(error)
        if "429" in err_msg or "rate limit" in err_msg.lower():
            await send_error_reply(
                interaction,
                "Discord is rate limiting requests. Please wait a minute and try again.",
                action_hint="This usually resolves quickly.",
            )
        elif "Missing Access" in err_msg or "50013" in err_msg:
            await send_error_reply(
                interaction,
                "I need additional permissions (e.g. **Manage Messages**, **Send Messages**). "
                "Ask an admin to grant them for this channel.",
            )
        elif "Unknown Channel" in err_msg:
            await send_error_reply(interaction, "That channel no longer exists.")
        else:
            await send_error_reply(interaction, "An error occurred. Please try again later.")
        logger.warning(f"[commands] Discord API error: {error}")
        return

    orig = getattr(error, "original", None) if error_type_name == "CommandInvokeError" else None
    if orig is not None:
        orig_name = type(orig).__name__
        if orig_name in ("Forbidden", "HTTPException"):
            err_msg = str(orig)
            status = getattr(orig, "status", None)
            if status == 429 or "429" in err_msg or "rate limit" in err_msg.lower():
                retry_after = getattr(orig, "retry_after", 60)
                await send_error_reply(
                    interaction,
                    f"Discord is rate limiting. Wait **{int(retry_after)}s** and try again.",
                    action_hint="This usually resolves quickly.",
                )
            elif "Missing Access" in err_msg or "50013" in err_msg:
                await send_error_reply(
                    interaction,
                    "I need additional permissions (e.g. **Manage Messages**, **Send Messages**). "
                    "Ask an admin to grant them for this channel.",
                )
            elif "Unknown Channel" in err_msg:
                await send_error_reply(interaction, "That channel no longer exists.")
            else:
                await send_error_reply(interaction, "An error occurred. Please try again later.")
            logger.warning(f"[commands] Command invoke error: {orig}")
            return

        user_message, action_hint, error_code = classify_exception(orig)
        cmd_name = getattr(interaction.command, "qualified_name", None)
        record_error(
            error_code=error_code,
            command_name=cmd_name,
            guild_id=interaction.guild.id if interaction.guild else None,
            exc=orig,
            user_message=user_message,
        )
        logger.error(f"[commands] Command error ({error_code}): {orig}", exc_info=orig)
        await send_error_reply(
            interaction, user_message, action_hint=action_hint, error_code=error_code
        )
        await notify_mods_error_digest(
            bot,
            interaction,
            error_code=error_code,
            user_message=user_message,
            exc=orig,
        )
        return

    user_message, action_hint, error_code = classify_exception(error)
    cmd_name = getattr(interaction.command, "qualified_name", None)
    record_error(
        error_code=error_code,
        command_name=cmd_name,
        guild_id=interaction.guild.id if interaction.guild else None,
        exc=error,
        user_message=user_message,
    )
    logger.error(f"[commands] Unhandled command error ({error_code}): {error}", exc_info=error)
    await send_error_reply(
        interaction, user_message, action_hint=action_hint, error_code=error_code
    )
    await notify_mods_error_digest(
        bot,
        interaction,
        error_code=error_code,
        user_message=user_message,
        exc=error,
    )
