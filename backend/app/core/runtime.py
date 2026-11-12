"""Event-loop setup shared by the server launcher and scripts."""

import asyncio
import sys


def use_selector_loop() -> None:
    """psycopg's async driver cannot use the Windows Proactor loop (the default on Windows)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
