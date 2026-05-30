"""Temp VC permission helpers: staff roles, overwrite seeding, panel access."""
from __future__ import annotations

from typing import Mapping, Optional, Union

import discord

from core.config import MOD_ROLE_NAME, MOD_ROLE_NAMES
from core.utils import is_mod
from database import get_guild_setting

OverwriteTarget = Union[discord.Role, discord.Member, discord.Object]
OverwriteMap = dict[OverwriteTarget, discord.PermissionOverwrite]

VC_OWNER_PERMS = {
    "view_channel": True,
    "connect": True,
    "manage_channels": True,
    "move_members": True,
    "mute_members": True,
    "deafen_members": True,
}

VC_STAFF_PERMS = {
    "view_channel": True,
    "connect": True,
    "speak": True,
    "manage_channels": True,
    "move_members": True,
    "mute_members": True,
    "deafen_members": True,
}

GUILD_VC_STAFF_SETTING = "vc_staff_role_ids"


def env_mod_role_names() -> list[str]:
    """Role names from MOD_ROLE_NAME / MOD_ROLE_NAMES env vars."""
    names: list[str] = []
    seen: set[str] = set()
    for name in [MOD_ROLE_NAME, *MOD_ROLE_NAMES]:
        if not name:
            continue
        key = name.strip().lower()
        if key and key not in seen:
            names.append(name.strip())
            seen.add(key)
    return names


def clone_overwrite(ow: discord.PermissionOverwrite) -> discord.PermissionOverwrite:
    allow, deny = ow.pair()
    return discord.PermissionOverwrite.from_pair(allow, deny)


def merge_overwrite(
    base: Optional[discord.PermissionOverwrite],
    **permissions: Optional[bool],
) -> discord.PermissionOverwrite:
    merged = clone_overwrite(base) if base else discord.PermissionOverwrite()
    for key, value in permissions.items():
        if value is not None:
            setattr(merged, key, value)
    return merged


def _roles_from_saved_ids(guild: discord.Guild, saved: str) -> list[discord.Role]:
    roles: list[discord.Role] = []
    seen: set[int] = set()
    for part in saved.split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        role = guild.get_role(int(part))
        if role and role.id not in seen:
            roles.append(role)
            seen.add(role.id)
    return roles


def _roles_from_env_names(guild: discord.Guild) -> list[discord.Role]:
    roles: list[discord.Role] = []
    seen: set[int] = set()
    for name in env_mod_role_names():
        role = discord.utils.get(guild.roles, name=name)
        if role and role.id not in seen:
            roles.append(role)
            seen.add(role.id)
    return roles


def _fallback_admin_role(guild: discord.Guild) -> Optional[discord.Role]:
    for role in sorted(guild.roles, key=lambda r: -r.position):
        if role.is_default():
            continue
        if role.permissions.administrator:
            return role
    return None


async def get_vc_staff_roles(guild: discord.Guild) -> list[discord.Role]:
    """Configured staff roles for temp VCs (guild setting, env names, then admin fallback)."""
    roles: list[discord.Role] = []
    seen: set[int] = set()

    saved = await get_guild_setting(guild.id, GUILD_VC_STAFF_SETTING)
    if saved:
        for role in _roles_from_saved_ids(guild, saved):
            if role.id not in seen:
                roles.append(role)
                seen.add(role.id)

    for role in _roles_from_env_names(guild):
        if role.id not in seen:
            roles.append(role)
            seen.add(role.id)

    if not roles:
        fallback = _fallback_admin_role(guild)
        if fallback:
            roles.append(fallback)

    return roles


def get_mod_role(guild: discord.Guild) -> Optional[discord.Role]:
    """First configured VC staff role (sync; env names + admin fallback only)."""
    env_roles = _roles_from_env_names(guild)
    if env_roles:
        return env_roles[0]
    return _fallback_admin_role(guild)


def member_has_vc_staff_role(member: discord.Member, staff_roles: list[discord.Role]) -> bool:
    member_ids = {r.id for r in member.roles}
    return any(r.id in member_ids for r in staff_roles)


def member_has_vc_staff_perms(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return bool(perms.manage_channels and perms.move_members)


async def can_manage_temp_vc(
    member: discord.Member,
    guild: discord.Guild,
    *,
    owner_id: Optional[int] = None,
) -> bool:
    """Owner, administrator, configured staff role, or Manage Channels + Move Members."""
    if owner_id is not None and member.id == owner_id:
        return True
    if is_mod(member):
        return True
    staff_roles = await get_vc_staff_roles(guild)
    if member_has_vc_staff_role(member, staff_roles):
        return True
    return member_has_vc_staff_perms(member)


def seed_overwrites_from_channels(
    guild: discord.Guild,
    *channels: Optional[Union[discord.CategoryChannel, discord.VoiceChannel]],
) -> OverwriteMap:
    """Copy role overwrites from category/hub channels (later sources override earlier)."""
    overwrites: OverwriteMap = {}
    for channel in channels:
        if channel is None:
            continue
        for target, ow in channel.overwrites.items():
            overwrites[target] = clone_overwrite(ow)
    if guild.default_role not in overwrites:
        overwrites[guild.default_role] = discord.PermissionOverwrite(
            view_channel=True, connect=True, speak=True
        )
    return overwrites


def apply_owner_overwrite(overwrites: OverwriteMap, owner: discord.Member) -> None:
    overwrites[owner] = discord.PermissionOverwrite(**VC_OWNER_PERMS)


def apply_staff_overwrites(overwrites: OverwriteMap, staff_roles: list[discord.Role]) -> None:
    for role in staff_roles:
        existing = overwrites.get(role)
        overwrites[role] = merge_overwrite(existing, **VC_STAFF_PERMS)


def build_temp_vc_overwrites(
    guild: discord.Guild,
    owner: discord.Member,
    *,
    category: Optional[discord.CategoryChannel],
    template_channel: Optional[discord.VoiceChannel],
    staff_roles: list[discord.Role],
) -> OverwriteMap:
    """Seed from category + hub, then layer owner and staff permissions."""
    overwrites = seed_overwrites_from_channels(guild, category, template_channel)
    apply_owner_overwrite(overwrites, owner)
    apply_staff_overwrites(overwrites, staff_roles)
    return overwrites


def apply_staff_overwrites_to_mapping(
    overwrites: Mapping[OverwriteTarget, discord.PermissionOverwrite],
    staff_roles: list[discord.Role],
) -> OverwriteMap:
    """Return a copy of channel overwrites with staff permissions ensured."""
    merged: OverwriteMap = {target: clone_overwrite(ow) for target, ow in overwrites.items()}
    apply_staff_overwrites(merged, staff_roles)
    return merged
