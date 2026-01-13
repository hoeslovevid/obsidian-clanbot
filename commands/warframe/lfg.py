"""LFG (Looking for Group) command for Warframe missions."""
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone

from utils import obsidian_embed
from bot import DB_PATH
import aiosqlite


# Common Warframe mission types
MISSION_TYPES = [
    "Elite Sanctuary Onslaught (ESO)",
    "Sanctuary Onslaught (SO)",
    "Steel Path",
    "Arbitration",
    "Sortie",
    "Eidolon Hunt",
    "Profit-Taker",
    "Exploiter Orb",
    "Void Fissure",
    "Relic Farming",
    "Resource Farming",
    "Affinity Farming",
    "Index",
    "Disruption",
    "Defense",
    "Survival",
    "Excavation",
    "Interception",
    "Spy",
    "Assassination",
    "Other",
]


class LFGView(discord.ui.View):
    """View with RSVP buttons for LFG posts."""
    
    def __init__(self, lfg_id: int):
        super().__init__(timeout=None)
        self.lfg_id = lfg_id
    
    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="✅")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Join the LFG group."""
        await self._handle_rsvp(interaction, "JOIN")
    
    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger, emoji="❌")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Leave the LFG group."""
        await self._handle_rsvp(interaction, "LEAVE")
    
    @discord.ui.button(label="Complete", style=discord.ButtonStyle.primary, emoji="✅")
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark the mission as complete (creator only)."""
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT creator_id, status FROM lfg_posts WHERE id=?",
                (self.lfg_id,)
            )
            post = await cur.fetchone()
            
            if not post:
                return await interaction.response.send_message("LFG post not found.", ephemeral=True)
            
            creator_id, status = post
            if interaction.user.id != creator_id:
                return await interaction.response.send_message("Only the creator can mark the mission as complete.", ephemeral=True)
            
            if status == "COMPLETED":
                return await interaction.response.send_message("This mission is already marked as complete.", ephemeral=True)
            
            # Update status
            await db.execute(
                "UPDATE lfg_posts SET status='COMPLETED' WHERE id=?",
                (self.lfg_id,)
            )
            await db.commit()
        
        # Update the embed
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.grey()
        embed.set_footer(text="✅ Mission Completed")
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("Mission marked as complete!", ephemeral=True)
    
    async def _handle_rsvp(self, interaction: discord.Interaction, response: str):
        """Handle RSVP (join/leave)."""
        async with aiosqlite.connect(DB_PATH) as db:
            # Get LFG post info
            cur = await db.execute(
                "SELECT creator_id, max_players, status FROM lfg_posts WHERE id=?",
                (self.lfg_id,)
            )
            post = await cur.fetchone()
            
            if not post:
                return await interaction.response.send_message("LFG post not found.", ephemeral=True)
            
            creator_id, max_players, status = post
            
            if status != "OPEN":
                return await interaction.response.send_message("This LFG post is no longer open.", ephemeral=True)
            
            # Check current RSVPs
            cur = await db.execute(
                "SELECT COUNT(*) FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN'",
                (self.lfg_id,)
            )
            current_count = (await cur.fetchone())[0]
            
            if response == "JOIN":
                if current_count >= max_players:
                    return await interaction.response.send_message(
                        f"This group is full ({max_players}/{max_players} players).",
                        ephemeral=True
                    )
                
                # Add or update RSVP
                await db.execute("""
                    INSERT INTO lfg_rsvps (lfg_id, user_id, response, created_at)
                    VALUES (?, ?, 'JOIN', ?)
                    ON CONFLICT(lfg_id, user_id) DO UPDATE SET response='JOIN', created_at=?
                """, (self.lfg_id, interaction.user.id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
            else:  # LEAVE
                await db.execute(
                    "DELETE FROM lfg_rsvps WHERE lfg_id=? AND user_id=?",
                    (self.lfg_id, interaction.user.id)
                )
            
            await db.commit()
            
            # Get updated RSVP list
            cur = await db.execute(
                "SELECT user_id FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN' ORDER BY created_at",
                (self.lfg_id,)
            )
            rsvps = await cur.fetchall()
            current_count = len(rsvps)
        
        # Update embed
        embed = interaction.message.embeds[0]
        
        # Rebuild RSVP list
        rsvp_list = ""
        for i, (user_id,) in enumerate(rsvps[:max_players], 1):
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            rsvp_list += f"{i}. {username}\n"
        
        if current_count < max_players:
            rsvp_list += f"\n_{max_players - current_count} slot(s) remaining_"
        else:
            rsvp_list += "\n_**Group is full!**_"
        
        # Update the RSVP field
        for i, field in enumerate(embed.fields):
            if field.name == "Players":
                embed.set_field_at(i, name="Players", value=rsvp_list or "No players yet", inline=False)
                break
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        action = "joined" if response == "JOIN" else "left"
        await interaction.followup.send(f"You {action} the group! ({current_count}/{max_players})", ephemeral=True)


def setup(bot):
    """Register the lfg command."""
    @bot.tree.command(name="lfg", description="Create a Looking for Group post for a Warframe mission.")
    @app_commands.describe(
        mission_type="Type of mission",
        max_players="Maximum number of players needed (default: 4)",
        description="Optional description or notes",
        duration_hours="Auto-expire after this many hours (default: 24, max: 168)"
    )
    @app_commands.choices(mission_type=[
        app_commands.Choice(name=mt, value=mt) for mt in MISSION_TYPES
    ])
    async def lfg(
        interaction: discord.Interaction,
        mission_type: app_commands.Choice[str],
        max_players: int = 4,
        description: str = "",
        duration_hours: int = 24
    ):
        """Create an LFG post for a Warframe mission."""
        # Validate max_players
        if max_players < 1 or max_players > 8:
            return await interaction.response.send_message(
                "Max players must be between 1 and 8.",
                ephemeral=True
            )
        
        # Validate duration
        if duration_hours < 1 or duration_hours > 168:
            duration_hours = 24
        
        # Calculate expiry time
        expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        
        # Create LFG post
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO lfg_posts (guild_id, channel_id, message_id, creator_id, mission_type, player_count, max_players, description, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """, (
                interaction.guild.id,
                interaction.channel.id,
                0,  # Will be updated after message is sent
                interaction.user.id,
                mission_type.value,
                1,  # Creator counts as 1
                max_players,
                description[:500] if description else None,
                datetime.now(timezone.utc).isoformat(),
                expires_at.isoformat(),
            ))
            await db.commit()
            
            # Get the LFG ID
            cur = await db.execute("SELECT last_insert_rowid()")
            lfg_id = (await cur.fetchone())[0]
        
        # Create embed
        mission_name = mission_type.value
        desc = f"**Mission:** {mission_name}\n"
        desc += f"**Created by:** {interaction.user.mention}\n"
        desc += f"**Players:** 1/{max_players}\n"
        if description:
            desc += f"\n**Notes:** {description}\n"
        desc += f"\n**Expires:** <t:{int(expires_at.timestamp())}:R>"
        
        embed = obsidian_embed(
            "🔍 Looking for Group",
            desc,
            color=discord.Color.blue(),
            footer=f"LFG ID: {lfg_id} • Click buttons below to join/leave",
        )
        
        # Add players field
        embed.add_field(
            name="Players",
            value=f"1. {interaction.user.display_name}\n\n_{max_players - 1} slot(s) remaining_",
            inline=False
        )
        
        # Create view with buttons
        view = LFGView(lfg_id)
        
        # Send message
        await interaction.response.send_message(embed=embed, view=view)
        
        # Get the message ID from the response
        message = await interaction.original_response()
        message_id = message.id
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE lfg_posts SET message_id=? WHERE id=?",
                (message_id, lfg_id)
            )
            await db.commit()
        
        # Register the view for persistence
        bot.add_view(view)
        
        # Add creator as first RSVP
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO lfg_rsvps (lfg_id, user_id, response, created_at)
                VALUES (?, ?, 'JOIN', ?)
            """, (lfg_id, interaction.user.id, datetime.now(timezone.utc).isoformat()))
            await db.commit()
