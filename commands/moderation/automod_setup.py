"""Auto-moderation setup command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from bot import DB_PATH
from database import get_auto_mod_settings, update_auto_mod_settings
import aiosqlite


def setup(bot):
    """Register the automod_setup command."""
    @bot.tree.command(name="automod_setup", description="Configure auto-moderation settings (moderators only).")
    @app_commands.describe(
        feature="Which feature to configure",
        enabled="Enable or disable the feature",
        threshold="Threshold value (for spam/caps/mentions)",
        interval="Time interval in seconds (for spam detection)",
        action="Punishment action when violation is detected",
        duration="Duration in minutes for timeout/ban (optional)",
        log_channel="Channel to log violations (optional)"
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Enable/Disable All", value="all"),
        app_commands.Choice(name="Spam Detection", value="spam"),
        app_commands.Choice(name="Caps Lock Filter", value="caps"),
        app_commands.Choice(name="Link Filter", value="links"),
        app_commands.Choice(name="Mention Limit", value="mention"),
    ])
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    @app_commands.choices(action=[
        app_commands.Choice(name="Delete Message", value="delete"),
        app_commands.Choice(name="Delete + Warn", value="warn"),
        app_commands.Choice(name="Delete + Timeout", value="timeout"),
        app_commands.Choice(name="Delete + Kick", value="kick"),
    ])
    async def automod_setup(
        interaction: discord.Interaction,
        feature: app_commands.Choice[str],
        enabled: app_commands.Choice[str] = None,
        threshold: int = None,
        interval: int = None,
        action: app_commands.Choice[str] = None,
        duration: int = None,
        log_channel: discord.TextChannel = None
    ):
        """Configure auto-moderation settings."""
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
        
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Error",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        guild_id = interaction.guild.id
        feature_value = feature.value
        
        # Get current settings
        current_settings = await get_auto_mod_settings(guild_id)
        
        updates = {}
        
        if feature_value == "all":
            if not enabled:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Error",
                        "Please specify whether to enable or disable auto-moderation.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            updates["enabled"] = enabled.value == "enable"
            
        elif feature_value == "spam":
            if enabled:
                updates["spam_enabled"] = enabled.value == "enable"
            if threshold is not None:
                if threshold < 2 or threshold > 20:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Error",
                            "Spam threshold must be between 2 and 20 messages.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                updates["spam_threshold"] = threshold
            if interval is not None:
                if interval < 5 or interval > 60:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Error",
                            "Spam interval must be between 5 and 60 seconds.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                updates["spam_interval"] = interval
                
        elif feature_value == "caps":
            if enabled:
                updates["caps_enabled"] = enabled.value == "enable"
            if threshold is not None:
                if threshold < 50 or threshold > 100:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Error",
                            "Caps threshold must be between 50 and 100 percent.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                updates["caps_threshold"] = threshold
                
        elif feature_value == "links":
            if enabled:
                updates["links_enabled"] = enabled.value == "enable"
                
        elif feature_value == "mention":
            if enabled:
                updates["mention_enabled"] = enabled.value == "enable"
            if threshold is not None:
                if threshold < 3 or threshold > 20:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Error",
                            "Mention limit must be between 3 and 20 mentions.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                updates["mention_limit"] = threshold
        
        # General settings
        if action:
            updates["punishment_action"] = action.value
        if duration is not None:
            if duration < 1 or duration > 1440:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Error",
                        "Punishment duration must be between 1 and 1440 minutes (24 hours).",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            updates["punishment_duration"] = duration
        if log_channel:
            updates["log_channel_id"] = log_channel.id
        
        # Apply updates
        await update_auto_mod_settings(guild_id, **updates)
        
        # Build response
        feature_names = {
            "all": "Auto-Moderation",
            "spam": "Spam Detection",
            "caps": "Caps Lock Filter",
            "links": "Link Filter",
            "mention": "Mention Limit"
        }
        
        fields = [("🔧 Feature", feature_names.get(feature_value, feature_value), True)]
        
        if enabled:
            fields.append(("✅ Status", "Enabled" if enabled.value == "enable" else "Disabled", True))
        if threshold is not None:
            fields.append(("📊 Threshold", str(threshold), True))
        if interval is not None:
            fields.append(("⏱️ Interval", f"{interval}s", True))
        if action:
            fields.append(("⚖️ Punishment", action.value.title(), True))
        if duration is not None:
            fields.append(("⏰ Duration", f"{duration} minutes", True))
        if log_channel:
            fields.append(("📝 Log Channel", log_channel.mention, True))
        
        embed = obsidian_embed(
            "✅ Auto-Moderation Updated",
            f"Settings for **{feature_names.get(feature_value, feature_value)}** have been updated.",
            color=discord.Color.green(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
