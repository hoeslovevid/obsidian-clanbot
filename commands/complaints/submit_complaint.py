"""Submit complaint command."""
import discord
from discord import app_commands

from utils import obsidian_embed


def setup(bot, group=None):
    """Register the submit_complaint command."""
    command_decorator = group.command(name="submit_complaint", description="Submit additional information to an existing complaint/help request case.") if group else bot.tree.command(name="submit_complaint", description="Submit additional information to an existing complaint/help request case.")
    
    @command_decorator
    @app_commands.describe(case_id="Your case id (e.g., OBS-...)", details="Additional details / links / screenshots")
    async def submit_complaint(interaction: discord.Interaction, case_id: str, details: str):
        # Import bot-specific functions inside to avoid circular imports
        from bot import ensure_core_channels, resolve_channel_id, log_complaint_action
        from bot import COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME, DB_PATH
        import aiosqlite
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id, staff_thread_id FROM complaints WHERE guild_id=? AND case_id=?",
                (interaction.guild.id, case_id),
            )
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message("Case not found.", ephemeral=True)

        user_id, staff_thread_id = int(row[0]), int(row[1] or 0)
        if user_id != interaction.user.id:
            return await interaction.response.send_message("You can only add info to your own case.", ephemeral=True)

        await ensure_core_channels(interaction.guild)
        complaints_id = await resolve_channel_id(interaction.guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
        ch = interaction.guild.get_channel(complaints_id) if complaints_id else None

        embed = obsidian_embed(
            f"Case Addendum • {case_id}",
            details[:2000],
            color=discord.Color.orange(),
            author=interaction.user,
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            footer=f"Case: {case_id} • User addendum",
            client=interaction.client,
        )

        if isinstance(ch, discord.TextChannel):
            await ch.send(embed=embed)

        if staff_thread_id:
            thread = interaction.guild.get_thread(staff_thread_id)
            if thread:
                try:
                    await thread.send(embed=embed)
                except Exception:
                    pass

        await log_complaint_action(interaction.guild, case_id, interaction.user.id, "USER_ADDENDUM", details[:200])
        await interaction.response.send_message("Addendum submitted.", ephemeral=True)
