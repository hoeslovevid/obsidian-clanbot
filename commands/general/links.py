"""Links command - quick access to Warframe and server links."""
import json
import discord
from discord import app_commands

from core.utils import obsidian_embed, EMBED_COLORS, is_mod
from core.config import BOT_WEBSITE
from database import get_guild_setting, set_guild_setting

DEFAULT_LINKS = [
    ("Wiki", "https://warframe.fandom.com/wiki/WARFRAME_Wiki"),
    ("Warframe Market", "https://warframe.market"),
    ("Drop Tables", "https://warframe.fandom.com/wiki/Module:DropTables/data"),
    ("Builds (Overframe)", "https://overframe.gg"),
]


def setup(bot, group=None):
    cmd = group.command(name="links", description="Quick links: Wiki, Market, Drop Tables, and server links.") if group else bot.tree.command(name="links", description="Quick links: Wiki, Market, Drop Tables, and server links.")

    @cmd
    async def links(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        links_list: list[tuple[str, str]] = []
        if BOT_WEBSITE:
            links_list.append(("Obsidian Overseer", BOT_WEBSITE))
        links_list.extend(DEFAULT_LINKS)
        custom_json = await get_guild_setting(interaction.guild.id, "custom_links") if interaction.guild else None
        if custom_json:
            try:
                custom = json.loads(custom_json)
                if isinstance(custom, list):
                    for item in custom:
                        if isinstance(item, dict) and item.get("name") and item.get("url"):
                            links_list.append((item["name"], item["url"]))
            except (json.JSONDecodeError, TypeError):
                pass
        lines = ["**Quick Links**\n"]
        for name, url in links_list[:15]:
            lines.append(f"• [{name}]({url})")
        desc = "\n".join(lines)
        embed = obsidian_embed(
            "Quick Links",
            desc,
            color=EMBED_COLORS["general"],
            footer="Use /general about for bot info • /help for commands",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

