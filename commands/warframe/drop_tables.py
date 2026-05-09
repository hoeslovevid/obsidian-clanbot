"""Drop tables - find where Warframe items drop."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, EMBED_COLORS


def setup(bot, group=None):
    cmd = group.command(name="drop", description="Find where items drop (links to Wiki drop tables).") if group else bot.tree.command(name="drop", description="Find where items drop.")

    @cmd
    @app_commands.describe(item="Item name (e.g. Ash Prime Neuroptics)")
    async def drop(interaction: discord.Interaction, item: str):
        await interaction.response.defer(ephemeral=True)
        q = (item or "").strip().replace(" ", "+")
        wiki_url = f"https://warframe.fandom.com/wiki/Special:Search?query={q}&scope=internal&contentType=page"
        drop_url = "https://warframe.fandom.com/wiki/Module:DropTables/data"
        embed = obsidian_embed(
            "Drop Tables",
            f"**Search:** [{item or 'Item'}]({wiki_url})\n\n"
            f"**Full drop tables:** [Wiki Drop Tables]({drop_url})\n\n"
            f"_Tip: Search for the exact item name (e.g. 'Ash Prime Neuroptics') for best results._",
            color=EMBED_COLORS["warframe"],
            footer="See also: /warframe resource, /trading trade_price",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
