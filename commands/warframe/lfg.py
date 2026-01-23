"""LFG (Looking for Group) command for Warframe missions."""
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone

from utils import obsidian_embed, get_mod_role
from bot import DB_PATH
import aiosqlite


# Common Warframe mission types
MISSION_TYPES = [
    "Elite SO (ESO)",
    "Sanctuary SO",
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
        # Set custom_id for each button to make them persistent
        # Custom IDs must be unique per LFG post
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.label == "Join":
                    item.custom_id = f"lfg:{lfg_id}:join"
                elif item.label == "Leave":
                    item.custom_id = f"lfg:{lfg_id}:leave"
                elif item.label == "Complete":
                    item.custom_id = f"lfg:{lfg_id}:complete"
    
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
        
        # Delete the message instead of editing it
        try:
            # Defer first so we can delete the message
            await interaction.response.defer(ephemeral=True)
            # Delete the LFG message
            await interaction.message.delete()
            await interaction.followup.send("Mission marked as complete! The LFG post has been removed.", ephemeral=True)
        except discord.errors.NotFound:
            # Message already deleted (maybe by another action)
            try:
                await interaction.followup.send("Mission marked as complete!", ephemeral=True)
            except Exception:
                pass  # Interaction might be expired
        except Exception as e:
            # If deletion fails (e.g., missing permissions), fall back to editing
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.light_grey()
            embed.set_footer(text="✅ Mission Completed")
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            try:
                # Try to edit the message
                await interaction.message.edit(embed=embed, view=self)
                await interaction.followup.send("Mission marked as complete! (Could not delete message - missing permissions?)", ephemeral=True)
            except Exception:
                # If editing also fails, just send confirmation
                try:
                    await interaction.followup.send("Mission marked as complete!", ephemeral=True)
                except Exception:
                    pass  # Interaction might be expired
    
    async def _handle_rsvp(self, interaction: discord.Interaction, response: str):
        """Handle RSVP (join/leave)."""
        async with aiosqlite.connect(DB_PATH) as db:
            # Get LFG post info including thread_id
            cur = await db.execute(
                "SELECT creator_id, max_players, status, thread_id FROM lfg_posts WHERE id=?",
                (self.lfg_id,)
            )
            post = await cur.fetchone()
            
            if not post:
                return await interaction.response.send_message("LFG post not found.", ephemeral=True)
            
            creator_id, max_players, status, thread_id = post
            
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
        
        # Update thread permissions if thread exists
        if thread_id:
            try:
                thread = interaction.guild.get_thread(thread_id)
                if thread:
                    if response == "JOIN":
                        # Add user to thread permissions
                        await thread.set_permissions(
                            interaction.user,
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True
                        )
                    else:  # LEAVE
                        # Remove user from thread permissions (unless they're the creator)
                        if interaction.user.id != creator_id:
                            await thread.set_permissions(
                                interaction.user,
                                view_channel=False,
                                send_messages=False
                            )
            except Exception as e:
                # If thread permission update fails, log but continue
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to update thread permissions for LFG {self.lfg_id}: {e}")
        
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
        thread_mention = ""
        if thread_id:
            try:
                thread = interaction.guild.get_thread(thread_id)
                if thread:
                    thread_mention = f" Check the thread: {thread.mention}"
            except Exception:
                pass
        await interaction.followup.send(f"You {action} the group! ({current_count}/{max_players}){thread_mention}", ephemeral=True)


def setup(bot, group=None):
    """Register the lfg command."""
    command_decorator = group.command(name="lfg", description="Create a Looking for Group post for a Warframe mission.") if group else bot.tree.command(name="lfg", description="Create a Looking for Group post for a Warframe mission.")
    
    @command_decorator
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
        
        # Create embed with better formatting
        mission_name = mission_type.value
        
        fields = [
            ("🎯 Mission", mission_name, True),
            ("👤 Created by", interaction.user.mention, True),
            ("⏰ Expires", f"<t:{int(expires_at.timestamp())}:R>", True),
        ]
        
        if description:
            fields.append(("📝 Notes", description[:500], False))
        
        # Add players field
        fields.append(("👥 Players", f"1. {interaction.user.display_name}\n\n_{max_players - 1} slot(s) remaining_", False))
        
        embed = obsidian_embed(
            "🔍 Looking for Group",
            "",
            color=discord.Color.blue(),
            fields=fields,
            footer=f"LFG ID: {lfg_id} • Click buttons below to join/leave",
            client=interaction.client,
        )
        
        # Create view with buttons
        view = LFGView(lfg_id)
        
        # Send message
        await interaction.response.send_message(embed=embed, view=view)
        
        # Get the message ID from the response
        message = await interaction.original_response()
        message_id = message.id
        
        # Create a thread for this LFG post
        thread = None
        thread_id = None
        try:
            # Create thread name with creator and mission (max 100 chars)
            creator_name = interaction.user.display_name or interaction.user.name
            # Format: "CreatorName - Mission Type"
            thread_name = f"{creator_name} - {mission_name}"
            
            # Truncate if too long (Discord limit is 100 chars)
            if len(thread_name) > 100:
                # Try to fit both names by truncating mission name
                max_mission_len = 100 - len(creator_name) - 3  # 3 for " - "
                if max_mission_len > 0:
                    thread_name = f"{creator_name} - {mission_name[:max_mission_len]}"
                else:
                    # If creator name is too long, just use mission name
                    thread_name = mission_name[:100]
            
            # Create thread with auto-archive duration
            thread = await message.create_thread(
                name=thread_name,
                auto_archive_duration=1440,  # 24 hours
                reason="LFG group discussion thread"
            )
            thread_id = thread.id
            
            # Set up thread permissions: only creator, RSVPs, and moderators can see it
            # First, deny @everyone from viewing
            await thread.edit(
                overwrites={
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)
                }
            )
            
            # Allow creator to view
            creator = interaction.guild.get_member(interaction.user.id)
            if creator:
                await thread.set_permissions(
                    creator,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            
            # Allow moderators to view
            mod_role = get_mod_role(interaction.guild)
            if mod_role:
                await thread.set_permissions(
                    mod_role,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True
                )
            
            # Send welcome message in thread
            welcome_msg = f"Welcome to the {mission_name} LFG thread!\n\n"
            welcome_msg += f"This thread is for coordinating with {interaction.user.mention} and other players who join.\n"
            welcome_msg += "Only the creator, RSVPs, and moderators can see this thread."
            await thread.send(welcome_msg)
            
        except Exception as e:
            # If thread creation fails, log but continue
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create thread for LFG {lfg_id}: {e}")
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE lfg_posts SET message_id=?, thread_id=? WHERE id=?",
                (message_id, thread_id, lfg_id)
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
