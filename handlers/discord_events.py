"""Discord gateway event registration (extracted from bot/app.py)."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore


def _find_similar_commands(typed: str, all_commands: list[str], max_suggestions: int = 3) -> list[str]:
    typed_lower = typed.lower().strip()
    if not typed_lower:
        return []
    suggestions = []
    for c in all_commands:
        cl = c.lower()
        if cl == typed_lower:
            return []
        if cl.startswith(typed_lower) or typed_lower in cl:
            suggestions.append(c)
    suggestions.sort(key=lambda x: (not x.lower().startswith(typed_lower), len(x)))
    return suggestions[:max_suggestions]


def register_discord_events(bot: discord.Client) -> None:
    """Attach all @bot.event handlers and the app-command error handler."""

    @bot.event
    async def on_message(message: discord.Message):
        from handlers.message_events import handle_on_message

        await handle_on_message(bot, message)

    @bot.event
    async def on_voice_state_update(
        member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        from handlers.voice_events import handle_voice_state_update

        await handle_voice_state_update(bot, member, before, after)

    @bot.event
    async def on_interaction(interaction: discord.Interaction):
        from handlers.interaction_router import handle_interaction

        await handle_interaction(bot, interaction)

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        from handlers.guild_events import handle_guild_join

        await handle_guild_join(bot, guild)

    @bot.event
    async def on_guild_remove(guild: discord.Guild):
        from handlers.guild_events import handle_guild_remove

        await handle_guild_remove(bot, guild)

    @bot.event
    async def on_ready():
        from handlers.startup import run_startup

        await run_startup(bot)

    @bot.event
    async def on_member_join(member: discord.Member):
        from handlers.member_events import handle_member_join

        await handle_member_join(bot, member)

    @bot.event
    async def on_member_remove(member: discord.Member):
        from handlers.member_events import handle_member_remove

        await handle_member_remove(bot, member)

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
        from handlers.reactions import handle_raw_reaction_add

        await handle_raw_reaction_add(bot, payload)

    @bot.event
    async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
        from handlers.reactions import handle_raw_reaction_remove

        await handle_raw_reaction_remove(bot, payload)

    @bot.event
    async def on_message_delete(message: discord.Message):
        from handlers.message_logs import handle_message_delete

        await handle_message_delete(bot, message)

    @bot.event
    async def on_message_edit(before: discord.Message, after: discord.Message):
        from handlers.message_logs import handle_message_edit

        await handle_message_edit(bot, before, after)

    @bot.event
    async def on_member_ban(guild: discord.Guild, user: discord.User):
        from handlers.message_logs import handle_member_ban

        await handle_member_ban(bot, guild, user)

    @bot.event
    async def on_app_command_completion(interaction: discord.Interaction, command):
        from handlers.command_tracking import handle_app_command_completion

        await handle_app_command_completion(bot, interaction, command)

    @bot.event
    async def on_member_update(before: discord.Member, after: discord.Member):
        from handlers.message_logs import handle_member_update

        await handle_member_update(bot, before, after)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        from core.error_handling import handle_app_command_error

        await handle_app_command_error(
            bot,
            interaction,
            error,
            find_similar_commands=_find_similar_commands,
        )
