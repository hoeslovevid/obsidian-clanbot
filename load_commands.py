"""
Command loader - imports and registers all commands after bot is created.
This avoids circular import issues.
"""
import importlib
import os

def load_commands(bot):
    """Load all command modules and register them with the bot."""
    command_modules = [
        "commands.general.help",
        "commands.general.setup_obsidian",
        # Add more as we create them
    ]
    
    for module_name in command_modules:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "setup"):
                module.setup(bot)
                print(f"[commands] Loaded {module_name}")
        except Exception as e:
            print(f"[commands] Failed to load {module_name}: {e}")
