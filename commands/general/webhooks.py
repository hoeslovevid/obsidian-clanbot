"""Webhook integration commands."""
import discord
from discord import app_commands
from typing import Optional
import aiohttp  # type: ignore

from core.utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore
import json
from datetime import datetime, timezone


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def setup(bot, group=None):
    """Register webhook commands."""
    
    command_decorator = group.command(name="webhook", description="Manage webhook endpoints for external integrations (moderators only).") if group else bot.tree.command(name="webhook", description="Manage webhook endpoints for external integrations (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        endpoint_name="Name for this webhook endpoint",
        webhook_url="Discord webhook URL",
        event_types="Comma-separated event types (e.g., 'member_join,member_leave')"
    )
    async def webhook(
        interaction: discord.Interaction,
        action: str,
        endpoint_name: Optional[str] = None,
        webhook_url: Optional[str] = None,
        event_types: Optional[str] = None
    ):
        """Manage webhooks."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        if action.lower() == "add":
            if not endpoint_name or not webhook_url or not event_types:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameters",
                        "Please provide endpoint_name, webhook_url, and event_types.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Validate webhook URL
            if not webhook_url.startswith("https://discord.com/api/webhooks/"):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Webhook URL",
                        "Webhook URL must be a valid Discord webhook URL.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Validate event types
            valid_events = {
                "member_join", "member_leave", "member_ban", "member_kick",
                "message_delete", "message_edit", "role_change", "channel_update",
                "complaint_created", "complaint_updated", "event_created"
            }
            event_list = [e.strip() for e in event_types.split(",")]
            invalid_events = [e for e in event_list if e not in valid_events]
            if invalid_events:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Event Types",
                        f"Invalid event types: {', '.join(invalid_events)}\n"
                        f"Valid events: {', '.join(sorted(valid_events))}",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO webhook_endpoints 
                    (guild_id, endpoint_name, webhook_url, event_types, enabled, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (
                    interaction.guild.id,
                    endpoint_name,
                    webhook_url,
                    json.dumps(event_list),
                    now_utc().isoformat()
                ))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Webhook Added",
                    f"Webhook endpoint **{endpoint_name}** configured for events: {', '.join(event_list)}",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            if not endpoint_name:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameter",
                        "Please provide endpoint_name.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    DELETE FROM webhook_endpoints 
                    WHERE guild_id=? AND endpoint_name=?
                """, (interaction.guild.id, endpoint_name))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Webhook Removed",
                    f"Webhook endpoint **{endpoint_name}** has been removed.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "list":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT endpoint_name, webhook_url, event_types, enabled, created_at
                    FROM webhook_endpoints
                    WHERE guild_id=?
                """, (interaction.guild.id,))
                rows = await cur.fetchall()
            
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 No Webhooks",
                        "No webhook endpoints are configured.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            desc = ""
            for endpoint_name, webhook_url, event_types_json, enabled, created_at in rows:
                status = "✅" if enabled else "❌"
                event_list = json.loads(event_types_json) if event_types_json else []
                desc += f"{status} **{endpoint_name}**\n"
                desc += f"Events: {', '.join(event_list)}\n"
                desc += f"URL: `{webhook_url[:50]}...`\n\n"
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Webhook Endpoints",
                    desc,
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Action",
                    "Valid actions: `add`, `remove`, `list`",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
