# Credits: gogeta_gg
"""Offline startup smoke test: load every cog without logging in to Discord.

Usage (from the python-bot/ project root):

    python tests/smoke_cogs.py

Exits non-zero if any cog fails to load. This catches import errors, broken
`setup()` entry points, duplicate command names and syntax problems without
needing a bot token or network access.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TOKEN", "offline-smoke-test")

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

# Helper/data modules that live inside cogs/ but are not extensions.
HELPERS = {
    "ai_provider_pool", "antibetray_db", "antinuke_db", "apply_db", "apply_view",
    "automod_db", "command_controls_db", "cv2_test", "embed_builder_view",
    "emoji_vault_db", "giveaway_db", "giveaway_utils", "giveaway_view",
    "invite_tracker_db", "moderation_db", "prefix_db", "reaction_db",
    "security_ui", "security_ui_v2", "server_knowledge", "tickets_db",
    "tickets_view",
}


def cog_names() -> list[str]:
    cogs_dir = ROOT / "cogs"
    return sorted(
        path.stem
        for path in cogs_dir.glob("*.py")
        if path.stem != "__init__" and path.stem not in HELPERS
    )


async def main() -> int:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

    names = cog_names()
    failed: list[tuple[str, str]] = []
    loaded = 0

    for name in names:
        try:
            await bot.load_extension(f"cogs.{name}")
            loaded += 1
        except Exception as exc:  # noqa: BLE001 - report and keep going
            failed.append((name, f"{type(exc).__name__}: {exc}"))

    print()
    print(f"[smoke] loaded {loaded}/{len(names)} cogs offline")
    print(f"[smoke] slash commands: {len(bot.tree.get_commands())}")
    print(f"[smoke] prefix commands: {sum(1 for _ in bot.walk_commands())}")

    if failed:
        print()
        for name, error in failed:
            print(f"[smoke] FAILED {name}: {error}")
        return 1

    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
