"""Application setup command for moderators."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot):
    """Register the application_setup command."""
    @bot.tree.command(name="application_setup", description="Configure the clan application system (moderators only).")
    @app_commands.describe(
        channel="The channel where users can apply (leave empty to use current channel)",
        action="What to configure"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set Application Channel", value="set_channel"),
        app_commands.Choice(name="Add Question", value="add_question"),
        app_commands.Choice(name="Remove Question", value="remove_question"),
        app_commands.Choice(name="View Questions", value="view_questions"),
        app_commands.Choice(name="Clear All Questions", value="clear_questions"),
    ])
    async def application_setup(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: Optional[discord.TextChannel] = None
    ):
        """Configure the application system."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can use this command.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        action_value = action.value
        
        if action_value == "set_channel":
            target_channel = channel or interaction.channel
            if not isinstance(target_channel, discord.TextChannel):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Channel",
                        "Please specify a valid text channel.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO application_settings (guild_id, channel_id)
                    VALUES (?, ?)
                """, (interaction.guild.id, target_channel.id))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Application Channel Set",
                    f"Application channel set to {target_channel.mention}.\n\nUsers can now use `/application` in this channel to start an application.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action_value == "add_question":
            from modals import ApplicationQuestionModal
            modal = ApplicationQuestionModal(interaction.guild.id)
            await interaction.followup.send(
                "Please fill out the form to add a question.",
                ephemeral=True
            )
            try:
                await interaction.user.send(embed=obsidian_embed(
                    "Add Application Question",
                    "Please fill out the form below to add a question to the application.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ), view=None)
                await interaction.user.send("Use the button below to add a question:", view=ApplicationQuestionView(interaction.guild.id))
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Cannot Send DM",
                        "I cannot send you a DM. Please enable DMs from server members.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        elif action_value == "remove_question":
            # Get all questions
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, question_order, question_text
                    FROM application_questions
                    WHERE guild_id = ?
                    ORDER BY question_order
                """, (interaction.guild.id,))
                questions = await cur.fetchall()
            
            if not questions:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Questions",
                        "There are no questions configured yet.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Create a select menu for choosing which question to remove
            options = []
            for q_id, order, text in questions:
                display_text = text[:100] if len(text) <= 100 else text[:97] + "..."
                options.append(discord.SelectOption(
                    label=f"Question {order}",
                    description=display_text,
                    value=str(q_id)
                ))
            
            view = RemoveQuestionView(questions)
            select = discord.ui.Select(
                placeholder="Select a question to remove...",
                options=options[:25],  # Discord limit
                custom_id="remove_question_select"
            )
            view.add_item(select)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "Remove Question",
                    "Select a question to remove:",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                view=view,
                ephemeral=True
            )
        
        elif action_value == "view_questions":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT question_order, question_text
                    FROM application_questions
                    WHERE guild_id = ?
                    ORDER BY question_order
                """, (interaction.guild.id,))
                questions = await cur.fetchall()
            
            if not questions:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Questions",
                        "There are no questions configured yet. Use the 'Add Question' action to add questions.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            fields = []
            for order, text in questions:
                fields.append((f"Question {order}", text, False))
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "Application Questions",
                    f"Total questions: {len(questions)}",
                    color=discord.Color.blue(),
                    fields=fields,
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action_value == "clear_questions":
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    DELETE FROM application_questions
                    WHERE guild_id = ?
                """, (interaction.guild.id,))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Questions Cleared",
                    "All application questions have been removed.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )


class ApplicationQuestionView(discord.ui.View):
    """View with button to open question modal."""
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
    
    @discord.ui.button(label="Add Question", style=discord.ButtonStyle.primary, custom_id="add_question_btn")
    async def add_question_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from modals import ApplicationQuestionModal
        modal = ApplicationQuestionModal(self.guild_id)
        await interaction.response.send_modal(modal)


class RemoveQuestionView(discord.ui.View):
    """View for removing questions."""
    def __init__(self, questions: list):
        super().__init__(timeout=300)
        self.questions = questions
    
    @discord.ui.select(custom_id="remove_question_select")
    async def remove_question_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Only moderators can use this.", ephemeral=True)
        
        question_id = int(select.values[0])
        
        # Get question info before deleting
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT question_order, question_text
                FROM application_questions
                WHERE id = ?
            """, (question_id,))
            question_info = await cur.fetchone()
            
            if question_info:
                order, text = question_info
                # Delete the question
                await db.execute("""
                    DELETE FROM application_questions
                    WHERE id = ?
                """, (question_id,))
                
                # Reorder remaining questions
                await db.execute("""
                    UPDATE application_questions
                    SET question_order = question_order - 1
                    WHERE guild_id = (SELECT guild_id FROM application_questions WHERE id = ? LIMIT 1)
                    AND question_order > ?
                """, (question_id, order))
                await db.commit()
                
                await interaction.response.send_message(
                    embed=obsidian_embed(
                        "✅ Question Removed",
                        f"Question {order} has been removed:\n\n{text[:200]}",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("Question not found.", ephemeral=True)
