# Credits: gogeta_gg
"""Register the bot's slash commands with Discord, without running the bot.

`bot.py` already syncs on startup, but global commands can take up to an hour
to appear. This script lets you push them straight to one test guild, where
they show up immediately.

Usage (from the python-bot/ project root):

    python scripts/sync_commands.py --guild 123456789012345678   # instant, test server
    python scripts/sync_commands.py                              # global sync
    python scripts/sync_commands.py --guild 1234 --clear         # scope se commands hatao

Guild ID `.env` ke DISCORD_GUILD_ID se bhi aa sakta hai. Token `.env` ke
`TOKEN` se padha jata hai -- use command line pe mat do.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

try:
    from env_loader import load_clean_dotenv

    load_clean_dotenv(ROOT / ".env")
except Exception as exc:  # noqa: BLE001 - env loading must never be fatal here
    print(f"[sync] .env load nahi hua ({type(exc).__name__}); shell env use kar raha hoon.")

import aiohttp  # noqa: E402
import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

# Same rule bot.py uses: only cogs/*.py with a module-level setup() are
# extensions, everything else is a helper/data module.
EXCLUDED = {
    "__init__.py", "giveaway_view.py", "giveaway_utils.py", "giveaway_db.py",
    "moderation_db.py", "antinuke_db.py", "apply_db.py", "apply_view.py",
    "spam_whitelist_db.py", "automod_db.py", "antibetray_db.py",
    "invite_tracker_db.py", "reaction_db.py", "security_ui.py",
    "security_ui_v2.py", "tickets_db.py", "tickets_view.py", "emoji_vault_db.py",
    "prefix_db.py", "ai_provider_pool.py", "embed_builder_view.py",
    "command_controls_db.py",
}


def discover_cogs() -> list[str]:
    cogs_dir = ROOT / "cogs"
    # cv2_test is an interactive demo cog that bot.py keeps off unless opted in.
    demo_enabled = os.getenv("ENABLE_CV2_TEST_COG", "").strip().lower() in {"1", "true", "yes", "on"}
    names: list[str] = []
    for path in sorted(cogs_dir.glob("*.py")):
        if path.name in EXCLUDED:
            continue
        if path.name == "cv2_test.py" and not demo_enabled:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:  # noqa: BLE001
            print(f"[sync] skip {path.name}: parse fail ({type(exc).__name__})")
            continue
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup"
            for node in tree.body
        ):
            names.append(path.stem)
    return names


def build_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    return commands.Bot(command_prefix="!", intents=intents, help_command=None)


async def sync(guild_id: int | None, clear: bool) -> int:
    bot = build_bot()
    loaded, failed = 0, []
    for name in discover_cogs():
        try:
            await bot.load_extension(f"cogs.{name}")
            loaded += 1
        except Exception as exc:  # noqa: BLE001 - report all, keep going
            failed.append((name, f"{type(exc).__name__}: {exc}"))

    print(f"[sync] cogs loaded: {loaded}/{loaded + len(failed)}")
    for name, error in failed:
        print(f"[sync] FAILED cog {name}: {error}")

    local = sum(1 for _ in bot.tree.walk_commands())
    if local == 0:
        print("[sync] koi command nahi mila — pehle cogs ka load hona zaroori hai.")
        return 1
    print(f"[sync] local commands mili: {local}")

    await bot.login(os.environ["TOKEN"])
    try:
        target = discord.Object(id=guild_id) if guild_id else None

        if clear:
            bot.tree.clear_commands(guild=target)
            removed = await bot.tree.sync(guild=target)
            where = f"guild {guild_id}" if guild_id else "global"
            print(f"[sync] {len(removed)} command(s) cleared — {where} scope.")
            return 0

        if target is not None:
            # Guild scope instantly dikhta hai: global push se pehle test karne ke liye best.
            bot.tree.copy_global_to(guild=target)
            synced = await bot.tree.sync(guild=target)
            where = f"guild {guild_id} (turant visible)"
        else:
            synced = await bot.tree.sync()
            where = "global (propagate hone me ~1 ghanta lag sakta hai)"

        print(f"[sync] {len(synced)} command(s) Discord pe register ho gayi — {where}")
        for cmd in sorted(synced, key=lambda c: c.name):
            print(f"        /{cmd.name}")
        return 0 if not failed else 2
    finally:
        try:
            await bot.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Register this bot's slash commands with Discord.")
    parser.add_argument("--guild", type=int, default=None,
                        help="Guild ID for instant guild-scoped sync (default: DISCORD_GUILD_ID or global).")
    parser.add_argument("--clear", action="store_true", help="Remove registered commands from that scope.")
    args = parser.parse_args()

    guild_id = args.guild
    if guild_id is None:
        raw = os.getenv("DISCORD_GUILD_ID", "").strip()
        guild_id = int(raw) if raw.isdigit() else None

    token = os.getenv("TOKEN", "").strip()
    if not token or token.lower() in {"your_token_here", "replace_me", "changeme"}:
        print("[sync] TOKEN missing/placeholder hai — .env me daal ke dobara chalao.")
        return 1

    try:
        return asyncio.run(sync(guild_id, args.clear))
    except discord.LoginFailure:
        print("[sync] Discord ne token reject kiya (LoginFailure). Token check karo.")
        return 1
    except discord.HTTPException as exc:
        print(f"[sync] Discord API error: {type(exc).__name__}: {exc}")
        return 1
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        print(f"[sync] Discord tak connect nahi hua: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
