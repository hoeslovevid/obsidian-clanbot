"""Backward-compat shim — loop registry moved to tasks/registry.py."""
from tasks.registry import setup_tasks

__all__ = ["setup_tasks"]
