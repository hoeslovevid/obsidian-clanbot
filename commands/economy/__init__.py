"""
Economy command group.
Organizes all economy-related commands under /economy.
"""
import discord
from discord import app_commands

economy_group = app_commands.Group(name="economy", description="Economy and currency commands")
