"""Randomized leave message templates for member departures."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

FIXED_PREFIX = "[fixed]"
RANDOM_SENTINEL = "{random}"
DEFAULT_LEAVE_TEMPLATE = "{user} has left {server}. We now have {member_count} members."

# Full leave lines — placeholders: {user}, {server}, {member_count}
LEAVE_MESSAGE_TEMPLATES = (
    "{user} has left {server}. Safe travels, Tenno!",
    "{user} departed from {server}. Until next time.",
    "Farewell, {user}! {server} now has {member_count} members.",
    "{user} has left the Discord. What a shame.",
    "{user} slipped into the Void and left {server}.",
    "Another Tenno down: {user} has left {server}.",
    "{user} has logged off from {server}. o7",
    "Goodbye, {user}! We will miss you in {server}.",
    "{user} has left the server. The Lotus sends regards.",
    "{user} is no longer with us — {member_count} members remain in {server}.",
    "Press F to pay respects: {user} has left {server}.",
    "{user} has gone AFK from {server}... permanently.",
    "{user} has left {server}. May your builds always crit.",
    "So long, {user}! {server} is down to {member_count} members.",
    "{user} has disconnected from {server}.",
    "{user} left {server}. Hope to see you back in the Origin System.",
    "{user} has left the relay. {member_count} Tenno still remain.",
    "One less operator in {server}: {user} has departed.",
    "{user} has left {server}. The grind continues without them.",
    "{user} has left the clan. o7 Tenno.",
)


def pick_leave_template(template: str | None) -> str:
    """Choose the leave message template to format."""
    text = (template or "").strip()
    if text.startswith(FIXED_PREFIX):
        return text[len(FIXED_PREFIX) :].strip()
    return random.choice(LEAVE_MESSAGE_TEMPLATES)


def format_leave_message(member: "discord.Member", template: str | None) -> str:
    """Build the final leave announcement for a departing member."""
    message = pick_leave_template(template)
    message = message.replace("{user}", str(member))
    message = message.replace("{server}", member.guild.name)
    message = message.replace("{member_count}", str(member.guild.member_count or 0))
    return message
