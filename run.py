"""Entry point for local runs and Railway (see Procfile)."""
import asyncio

from bot.app import main

if __name__ == "__main__":
    asyncio.run(main())
