# Credits: gogeta_gg
"""Generate website/commands.json from the cogs that actually load.

The website (website/index.html) is pure static — this script only builds its
data, so the site always shows the real registered commands instead of a
hand-maintained list.

Usage (from the python-bot/ project root):
    python scripts/gen_site_data.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TOKEN", "site-data-generator")

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

from scripts.sync_commands import discover_cogs  # noqa: E402

OUT = ROOT / "website" / "commands.json"


def _cog_of(obj) -> str:
    """Which cog owns this app command. Groups have no binding of their own,
    so fall back to the first child that does."""
    binding = getattr(obj, "binding", None)
    if binding is not None:
        return getattr(type(binding), "__cog_name__", None) or "bot.py"
    for child in getattr(obj, "walk_commands", lambda: [])():
        child_binding = getattr(child, "binding", None)
        if child_binding is not None:
            return getattr(type(child_binding), "__cog_name__", None) or "bot.py"
    return "bot.py"


def _params_from_app(command) -> list[dict]:
    """Slash/hybrid command ke parameters (name, description, required, type)."""
    params = []
    for param in getattr(command, "parameters", []) or []:
        params.append({
            "name": param.name,
            "description": param.description or "",
            "required": bool(param.required),
            "type": getattr(param.type, "name", str(param.type)),
        })
    return params


def _params_from_prefix(command) -> list[dict]:
    """Pure prefix command ke params — clean_params signature se."""
    params = []
    try:
        for name, param in command.clean_params.items():
            if name in {"self", "ctx"}:
                continue
            required = param.default is param.empty
            annotation = getattr(param.annotation, "__name__", None)
            params.append({
                "name": name,
                "description": "",
                "required": required,
                "type": (annotation or "str").lower(),
            })
    except Exception:  # noqa: BLE001 - best effort only
        pass
    return params


def _permissions(command) -> list[str]:
    perms = getattr(command, "default_permissions", None)
    if perms is None:
        return []
    try:
        return [name for name, value in perms if value]
    except Exception:  # noqa: BLE001
        return []


def _usage(command) -> str:
    parts = []
    for param in command.get("params", []):
        parts.append(f"<{param['name']}>" if param["required"] else f"[{param['name']}]")
    prefix = "/" if command["type"] in {"slash", "slash+prefix", "group"} else ""
    return " ".join([f"{prefix}{command['name']}"] + parts)


async def build() -> dict:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

    loaded, failed = 0, []
    for name in discover_cogs():
        try:
            await bot.load_extension(f"cogs.{name}")
            loaded += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"cog": name, "error": f"{type(exc).__name__}: {exc}"})

    entries: dict[str, dict] = {}

    def add(name, cog, kind, description, group=None, params=None, perms=None, aliases=None):
        entry = entries.setdefault(name, {
            "name": name,
            "cog": cog,
            "type": kind,
            "description": description or "",
            "group": group,
            "params": params or [],
            "permissions": perms or [],
            "aliases": aliases or [],
        })
        # hybrid commands show up in both trees; the prefix pass knows better
        if entry["type"] == "slash" and kind == "slash+prefix":
            entry["type"] = kind
        if params:
            entry["params"] = params
        if perms:
            entry["permissions"] = perms
        if aliases:
            entry["aliases"] = aliases

    # prefix / hybrid pass — has the real prefix-side metadata
    for cmd in bot.walk_commands():
        if getattr(cmd, "parent", None):
            continue
        kind = "slash+prefix" if isinstance(cmd, commands.HybridCommand) else "prefix"
        app_command = getattr(cmd, "app_command", None)
        params = _params_from_app(app_command) if app_command is not None else _params_from_prefix(cmd)
        add(
            cmd.qualified_name,
            cmd.cog_name or "bot.py",
            kind,
            (cmd.description or cmd.help or "").strip().split("\n")[0],
            params=params,
            perms=_permissions(app_command) if app_command is not None else [],
            aliases=list(cmd.aliases or []),
        )

    # slash pass — plain slash commands + groups with their children
    for top in bot.tree.get_commands():
        cog = _cog_of(top)
        if isinstance(top, discord.app_commands.Group):
            add(top.name, cog, "group", top.description or "")
            for child in top.walk_commands():
                add(
                    child.qualified_name,
                    cog,
                    "slash",
                    child.description or "",
                    group=top.name,
                    params=_params_from_app(child),
                    perms=_permissions(child),
                )
        else:
            add(
                top.name,
                cog,
                "slash",
                top.description or "",
                params=_params_from_app(top),
                perms=_permissions(top),
            )

    for entry in entries.values():
        entry["usage"] = _usage(entry)

    by_cog: dict[str, list] = {}
    for entry in entries.values():
        by_cog.setdefault(entry["cog"], []).append(entry)

    cogs = [
        {"name": cog, "commands": sorted(cmds, key=lambda c: (c["group"] or "", c["name"]))}
        for cog, cmds in sorted(by_cog.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    ]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "totals": {
            "cogs_loaded": loaded,
            "cogs_failed": len(failed),
            "slash_top_level": len(bot.tree.get_commands()),
            "slash_all": sum(1 for _ in bot.tree.walk_commands()),
            "prefix": sum(1 for _ in bot.walk_commands()),
            "unique_commands": len(entries),
            "with_params": sum(1 for e in entries.values() if e["params"]),
        },
        "failed": failed,
        "cogs": cogs,
    }


def main() -> int:
    data = asyncio.run(build())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    t = data["totals"]
    print(f"[site] {OUT.relative_to(ROOT)} likh diya — {t['unique_commands']} commands, "
          f"{t['cogs_loaded']} cogs, {t['slash_all']} slash (incl. subcommands), "
          f"{t['with_params']} with parameters")
    for item in data["failed"]:
        print(f"[site] FAILED cog {item['cog']}: {item['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
