"""Application command for users to start applications."""
from __future__ import annotations

import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed
from database import DB_PATH, now_utc
import aiosqlite


async def start_application_process(interaction: discord.Interaction):
    """Start an application process - reusable function for both command and button."""
    # Helper function to send error messages (handles both response and followup)
    async def send_error(embed):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
            # Interaction expired or already handled, try followup as last resort
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass  # Can't send, that's okay
    
    # Check channel, existing app, and questions in one connection
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id FROM application_settings WHERE guild_id = ?
        """, (interaction.guild.id,))
        row = await cur.fetchone()
        if not row or not row[0]:
            await send_error(obsidian_embed(
                "❌ Application System Not Configured",
                "The application system has not been set up yet. Please contact a moderator.",
                color=discord.Color.red(),
                client=interaction.client,
            ))
            return
        app_channel_id = row[0]

        cur = await db.execute("""
            SELECT id FROM applications
            WHERE guild_id = ? AND user_id = ? AND status = 'IN_PROGRESS'
        """, (interaction.guild.id, interaction.user.id))
        existing = await cur.fetchone()
        if existing:
            await send_error(obsidian_embed(
                "❌ Application Already In Progress",
                "You already have an application in progress. Please complete it or wait for it to be reviewed.",
                color=discord.Color.red(),
                client=interaction.client,
            ))
            return

        cur = await db.execute("""
            SELECT COUNT(*) FROM application_questions WHERE guild_id = ?
        """, (interaction.guild.id,))
        count = (await cur.fetchone())[0]

    if count == 0:
        await send_error(obsidian_embed(
            "❌ No Questions Configured",
            "The application system has no questions configured yet. Please contact a moderator.",
            color=discord.Color.red(),
            client=interaction.client,
        ))
        return
    
    # Defer if not already done (for command interactions)
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
            # Already handled, continue with followup
            pass
    
    # Create application record
    created_at = now_utc().isoformat()
    application_id = None
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO applications (guild_id, user_id, status, current_question_index, created_at)
            VALUES (?, ?, 'IN_PROGRESS', 0, ?)
        """, (interaction.guild.id, interaction.user.id, created_at))
        await db.commit()
        
        cur = await db.execute("SELECT last_insert_rowid()")
        application_id = (await cur.fetchone())[0]
    
    if not application_id:
        await send_error(obsidian_embed(
            "❌ Error",
            "Failed to create application. Please try again.",
            color=discord.Color.red(),
            client=interaction.client,
        ))
        return
    
    # Send first question via DM
    await send_next_question(interaction.client, interaction.guild.id, interaction.user.id, application_id)
    
    # Send success message (always use followup since we've deferred by this point)
    try:
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Application Started",
                "I've sent you the first question via DM. Please check your DMs and answer the questions to complete your application.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
        # Interaction expired, that's okay
        pass


async def cancel_application(bot, guild_id: int, user_id: int, application_id: int, interaction: Optional[discord.Interaction] = None):
    """Cancel an in-progress application."""
    import asyncio
    
    # Retry logic for database locking issues
    max_retries = 3
    retry_delay = 0.1  # Start with 100ms
    
    for attempt in range(max_retries):
        try:
            # Use a single connection for all operations
            async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
                # Check if application exists and belongs to user
                cur = await db.execute("""
                    SELECT status, user_id FROM applications WHERE id = ? AND guild_id = ?
                """, (application_id, guild_id))
                row = await cur.fetchone()
            
                if not row:
                    if interaction:
                        try:
                            if interaction.response.is_done():
                                await interaction.followup.send("Application not found.", ephemeral=True)
                            else:
                                await interaction.response.send_message("Application not found.", ephemeral=True)
                        except Exception:
                            pass
                    return False
                
                status, app_user_id = row[0], row[1]
                
                # Check if it belongs to the user
                if app_user_id != user_id:
                    if interaction:
                        try:
                            if interaction.response.is_done():
                                await interaction.followup.send("This application does not belong to you.", ephemeral=True)
                            else:
                                await interaction.response.send_message("This application does not belong to you.", ephemeral=True)
                        except Exception:
                            pass
                    return False
                
                # Check if it's in progress
                if status != 'IN_PROGRESS':
                    if interaction:
                        try:
                            if interaction.response.is_done():
                                await interaction.followup.send(
                                    embed=obsidian_embed(
                                        "❌ Cannot Cancel",
                                        f"This application is already {status.lower()} and cannot be cancelled.",
                                        color=discord.Color.red(),
                                        client=bot,
                                    ),
                                    ephemeral=True
                                )
                            else:
                                await interaction.response.send_message(
                                    embed=obsidian_embed(
                                        "❌ Cannot Cancel",
                                        f"This application is already {status.lower()} and cannot be cancelled.",
                                        color=discord.Color.red(),
                                        client=bot,
                                    ),
                                    ephemeral=True
                                )
                        except Exception:
                            pass
                    return False
                
                # Cancel the application (all in the same connection)
                await db.execute("""
                    UPDATE applications
                    SET status = 'CANCELLED'
                    WHERE id = ?
                """, (application_id,))
                await db.commit()
                break  # Success, exit retry loop
                
        except aiosqlite.OperationalError as e:
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                # Wait before retrying with exponential backoff
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            else:
                # Re-raise if it's not a locking issue or we've exhausted retries
                raise
        except Exception as e:
            # For other errors, log and re-raise
            import logging
            logging.getLogger(__name__).error(f"Error cancelling application: {e}")
            raise
    
    # Notify user
    guild = bot.get_guild(guild_id)
    if guild:
        user = guild.get_member(user_id)
        if user:
            try:
                await user.send(
                    embed=obsidian_embed(
                        "❌ Application Cancelled",
                        "Your application has been cancelled. You can start a new application anytime.",
                        color=discord.Color.orange(),
                        client=bot,
                    )
                )
            except discord.Forbidden:
                pass
    
    # Send confirmation to interaction if provided
    if interaction:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Application Cancelled",
                        "Your application has been cancelled successfully.",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    embed=obsidian_embed(
                        "✅ Application Cancelled",
                        "Your application has been cancelled successfully.",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                    ephemeral=True
                )
        except Exception:
            pass
    
    return True


def setup(bot, group=None):
    """Register the application commands."""

    my_apps_decorator = group.command(name="my_applications", description="List your applications and their status.") if group else None
    if my_apps_decorator:
        @my_apps_decorator
        async def my_applications(interaction: discord.Interaction):
            """List user's applications."""
            if not interaction.guild:
                return await interaction.response.send_message(
                    embed=obsidian_embed("❌ Invalid Context", "Use in a server.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True)
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, status, created_at, submitted_at, reviewed_at
                    FROM applications WHERE guild_id=? AND user_id=?
                    ORDER BY created_at DESC LIMIT 10
                """, (interaction.guild.id, interaction.user.id))
                rows = await cur.fetchall()
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 No Applications",
                        "You haven't submitted any applications. Use `/community application` to apply.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            status_emoji = {"IN_PROGRESS": "⏳", "PENDING": "⏳", "APPROVED": "✅", "REJECTED": "❌", "CANCELLED": "🚫"}
            lines = []
            for app_id, status, created, submitted, reviewed in rows:
                emoji = status_emoji.get(status, "📋")
                dt_str = submitted or created
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    ts = int(dt.timestamp())
                    lines.append(f"{emoji} **#{app_id}** — {status} (<t:{ts}:R>)")
                except Exception:
                    lines.append(f"{emoji} **#{app_id}** — {status}")
            await interaction.followup.send(
                embed=obsidian_embed("📋 My Applications", "\n".join(lines), color=discord.Color.blue(), client=interaction.client),
                ephemeral=True,
            )

    # Main application command
    command_decorator = group.command(name="application", description="Start a clan application.") if group else bot.tree.command(name="application", description="Start a clan application.")
    
    @command_decorator
    async def application(interaction: discord.Interaction):
        """Start a clan application."""
        # Check if application channel is set (single query)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT channel_id FROM application_settings WHERE guild_id = ?
            """, (interaction.guild.id,))
            row = await cur.fetchone()

        if not row or not row[0]:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Application System Not Configured",
                    "The application system has not been set up yet. Please contact a moderator.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        app_channel_id = row[0]
        
        # Check if user is in the correct channel
        if interaction.channel.id != app_channel_id:
            app_channel = interaction.guild.get_channel(app_channel_id)
            channel_mention = app_channel.mention if app_channel else "the application channel"
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Wrong Channel",
                    f"Please use this command in {channel_mention}.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Use the shared function
        await start_application_process(interaction)
    
    # Cancel command
    cancel_decorator = group.command(name="cancel", description="Cancel your in-progress application.") if group else bot.tree.command(name="application_cancel", description="Cancel your in-progress application.")
    
    @cancel_decorator
    async def application_cancel(interaction: discord.Interaction):
        """Cancel an in-progress application."""
        await interaction.response.defer(ephemeral=True)
        
        # Find user's in-progress application and cancel in a single operation
        # This avoids opening multiple database connections
        import asyncio
        
        max_retries = 3
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
                    # Find user's in-progress application
                    cur = await db.execute("""
                        SELECT id FROM applications
                        WHERE guild_id = ? AND user_id = ? AND status = 'IN_PROGRESS'
                    """, (interaction.guild.id, interaction.user.id))
                    row = await cur.fetchone()
                
                    if not row:
                        return await interaction.followup.send(
                            embed=obsidian_embed(
                                "❌ No Active Application",
                                "You don't have an application in progress to cancel.",
                                color=discord.Color.red(),
                                client=interaction.client,
                            ),
                            ephemeral=True
                        )
                    
                    application_id = row[0]
                    
                    # Cancel the application in the same connection
                    await db.execute("""
                        UPDATE applications
                        SET status = 'CANCELLED'
                        WHERE id = ? AND guild_id = ? AND user_id = ? AND status = 'IN_PROGRESS'
                    """, (application_id, interaction.guild.id, interaction.user.id))
                    await db.commit()
                    
                    # Notify user
                    guild = interaction.guild
                    user = guild.get_member(interaction.user.id)
                    if user:
                        try:
                            await user.send(
                                embed=obsidian_embed(
                                    "❌ Application Cancelled",
                                    "Your application has been cancelled. You can start a new application anytime.",
                                    color=discord.Color.orange(),
                                    client=interaction.client,
                                )
                            )
                        except discord.Forbidden:
                            pass
                    
                    # Send confirmation
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "✅ Application Cancelled",
                            "Your application has been cancelled successfully.",
                            color=discord.Color.orange(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                    break  # Success, exit retry loop
                    
            except aiosqlite.OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    # Wait before retrying with exponential backoff
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue
                else:
                    # Re-raise if it's not a locking issue or we've exhausted retries
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Error",
                            "Failed to cancel application. Please try again in a moment.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                    raise
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error in application_cancel: {e}")
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Error",
                        "An error occurred while cancelling your application. Please try again.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
                raise


async def send_next_question(bot, guild_id: int, user_id: int, application_id: int):
    """Send the next question to the user via DM."""
    # Get the current question index
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT current_question_index FROM applications WHERE id = ?
        """, (application_id,))
        row = await cur.fetchone()
        if not row:
            return
        current_index = row[0]
        
        # Get all questions
        cur = await db.execute("""
            SELECT id, question_order, question_text
            FROM application_questions
            WHERE guild_id = ?
            ORDER BY question_order
        """, (guild_id,))
        questions = await cur.fetchall()
    
    if current_index >= len(questions):
        # All questions answered, submit application
        await submit_application(bot, guild_id, user_id, application_id)
        return
    
    question_id, order, question_text = questions[current_index]
    
    # Get user and send DM
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    
    user = guild.get_member(user_id)
    if not user:
        return
    
    # Create modal for the question
    from modals import ApplicationResponseModal
    modal = ApplicationResponseModal(application_id, question_id, question_text)
    
    try:
        # Send DM with question and button to answer
        embed = obsidian_embed(
            f"Application Question {order}/{len(questions)}",
            question_text,
            color=discord.Color.blue(),
            client=bot,
        )
        
        view = ApplicationQuestionView(modal, application_id)
        await user.send(embed=embed, view=view)
    except discord.Forbidden:
        # User has DMs disabled, we'll handle this in the interaction handler
        pass


class ApplicationQuestionView(discord.ui.View):
    """View with button to answer question."""
    def __init__(self, modal: ApplicationResponseModal, application_id: int):
        super().__init__(timeout=600)
        self.modal = modal
        self.application_id = application_id
    
    @discord.ui.button(label="Answer Question", style=discord.ButtonStyle.primary, custom_id="answer_question_btn")
    async def answer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(self.modal)
    
    @discord.ui.button(label="Cancel Application", style=discord.ButtonStyle.danger, custom_id="cancel_application_btn")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the application."""
        # Defer immediately
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
            pass
        
        await cancel_application(interaction.client, interaction.guild.id, interaction.user.id, self.application_id, interaction)


async def submit_application(bot, guild_id: int, user_id: int, application_id: int):
    """Submit the completed application."""
    from database import now_utc
    
    submitted_at = now_utc().isoformat()
    
    # Update application status
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE applications
            SET status = 'PENDING', submitted_at = ?
            WHERE id = ?
        """, (submitted_at, application_id))
        await db.commit()
        
        # Get all responses
        cur = await db.execute("""
            SELECT ar.question_id, aq.question_order, aq.question_text, ar.response_text
            FROM application_responses ar
            JOIN application_questions aq ON ar.question_id = aq.id
            WHERE ar.application_id = ?
            ORDER BY aq.question_order
        """, (application_id,))
        responses = await cur.fetchall()
        
        # Get application info
        cur = await db.execute("""
            SELECT user_id, created_at FROM applications WHERE id = ?
        """, (application_id,))
        app_info = await cur.fetchone()
    
    if not app_info:
        return
    
    # Get application channel
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id FROM application_settings WHERE guild_id = ?
        """, (guild_id,))
        row = await cur.fetchone()
    
    if not row or not row[0]:
        return
    
    app_channel = bot.get_guild(guild_id).get_channel(row[0])
    if not isinstance(app_channel, discord.TextChannel):
        return
    
    # Create embed with application
    user = bot.get_guild(guild_id).get_member(user_id)
    username = user.display_name if user else f"User {user_id}"
    
    fields = []
    for question_id, order, question_text, response_text in responses:
        fields.append((f"Question {order}", question_text, False))
        fields.append(("Answer", response_text[:1024], False))
    
    fields.append(("Status", "⏳ Pending Review", True))
    fields.append(("Application ID", f"#{application_id}", True))
    
    embed = obsidian_embed(
        "📝 New Clan Application",
        f"Application from {username}",
        color=discord.Color.blue(),
        author=user,
        fields=fields,
        client=bot,
    )
    
    # Create view for moderators
    from views import ApplicationManageView
    view = ApplicationManageView(application_id)
    bot.add_view(view)
    
    try:
        message = await app_channel.send(embed=embed, view=view)
        
        # Update message_id
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE applications SET message_id = ? WHERE id = ?
            """, (message.id, application_id))
            await db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error posting application: {e}")
    
    # Notify user
    try:
        if user:
            await user.send(
                embed=obsidian_embed(
                    "✅ Application Submitted",
                    "Your application has been submitted and is pending review. You will be notified once a decision has been made.",
                    color=discord.Color.green(),
                    client=bot,
                )
            )
    except discord.Forbidden:
        pass
