"""Cross-server communication system."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def create_alliance(guild_id: int, allied_guild_id: int, alliance_name: Optional[str] = None) -> int:
    """Create a server alliance. Returns alliance ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO server_alliances (guild_id, allied_guild_id, alliance_name, created_at, enabled)
            VALUES (?, ?, ?, ?, 1)
        """, (guild_id, allied_guild_id, alliance_name or f"Alliance {guild_id}-{allied_guild_id}", now_utc().isoformat()))
        await db.commit()
        
        cur = await db.execute("SELECT last_insert_rowid()")
        return (await cur.fetchone())[0]


async def get_alliances(guild_id: int) -> list:
    """Get all alliances for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, allied_guild_id, alliance_name, enabled
            FROM server_alliances
            WHERE guild_id=? AND enabled=1
        """, (guild_id,))
        return await cur.fetchall()


def setup(bot, group=None):
    """Register cross-server communication commands."""
    # Alliance command
    alliance_decorator = group.command(name="alliance", description="Manage server alliances (moderators only).") if group else bot.tree.command(name="alliance", description="Manage server alliances (moderators only).")
    
    @alliance_decorator
    @app_commands.describe(
        action="Action to perform",
        alliance_name="Name for the alliance"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Create", value="create"),
    ])
    async def alliance(interaction: discord.Interaction, action: str, alliance_name: Optional[str] = None):
        """Manage server alliances."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can manage alliances.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        
        if action == "list":
            alliances = await get_alliances(interaction.guild.id)
            
            if not alliances:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "🤝 Server Alliances",
                        "No active alliances found.",
                        color=discord.Color.blurple(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            fields = []
            for alliance_id, allied_guild_id, name, enabled in alliances[:10]:
                # Try to get guild name (would need bot to be in that server)
                guild_name = f"Server {allied_guild_id}"
                try:
                    from bot import bot as bot_instance
                    allied_guild = bot_instance.get_guild(allied_guild_id)
                    if allied_guild:
                        guild_name = allied_guild.name
                except:
                    pass
                
                fields.append((
                    f"Alliance #{alliance_id}",
                    f"**Name:** {name}\n"
                    f"**Allied Server:** {guild_name}\n"
                    f"**Status:** {'Active' if enabled else 'Inactive'}",
                    False
                ))
            
            embed = obsidian_embed(
                "🤝 Server Alliances",
                f"**Total:** {len(alliances)} active alliance(s)",
                color=discord.Color.blurple(),
                fields=fields,
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        elif action == "create":
            await interaction.followup.send(
                embed=obsidian_embed(
                    "ℹ️ Create Alliance",
                    "To create an alliance, both servers need to run this command.\n"
                    "Alliances require mutual agreement between server administrators.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
