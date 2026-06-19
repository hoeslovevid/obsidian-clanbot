"""
Background tasks package.

Loop definitions live in ``tasks/registry.py``. Call ``setup_tasks(bot)`` once
after the bot is ready to start all background loops.
"""
from tasks.registry import setup_tasks  # noqa: F401
