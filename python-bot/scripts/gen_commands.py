import asyncio, os, sys, importlib.util
sys.path.insert(0, os.getcwd()); os.environ.setdefault("TOKEN", "x")
import discord
from discord.ext import commands
spec = importlib.util.spec_from_file_location("smoke", "tests/smoke_cogs.py")
smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)


def cog_of(obj):
    b = getattr(obj, "binding", None)
    return getattr(type(b), "__cog_name__", None) if b else None


async def main():
    intents = discord.Intents.default(); intents.message_content = True; intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
    loaded = []
    for n in smoke.cog_names():
        try:
            await bot.load_extension(f"cogs.{n}"); loaded.append(n)
        except Exception as e:
            print("FAIL", n, e)

    # name -> (cog, type, description); hybrid commands walk both trees, so key
    # by name and let the prefix pass win (it knows it's a hybrid).
    entries = {}
    for c in bot.walk_commands():
        kind = "slash+prefix" if isinstance(c, commands.HybridCommand) else "prefix"
        entries[c.qualified_name] = (c.cog_name, kind, (c.description or c.help or "").strip().split("\n")[0][:120])

    for t in bot.tree.get_commands():
        cog = cog_of(t)
        if isinstance(t, discord.app_commands.Group):
            entries.setdefault(t.name, (cog, "slash group", (t.description or "")[:120]))
            for ch in t.walk_commands():
                entries.setdefault(ch.qualified_name, (cog, "slash", (ch.description or "")[:120]))
        else:
            entries.setdefault(t.name, (cog, "slash", (t.description or "")[:120]))

    by_cog = {}
    for name, (cog, kind, desc) in entries.items():
        by_cog.setdefault(cog or "bot.py (root)", []).append((name, kind, desc))

    total_slash = sum(1 for _ in bot.tree.walk_commands())
    total_prefix = sum(1 for _ in bot.walk_commands())
    out = [
        "# Commands — Gogeta's Pet", "",
        f"Auto-generated from the cogs that actually load (`{len(loaded)}` extensions). "
        "Regenerate with `python scripts/gen_commands.py` after adding a cog.", "",
        f"**Totals:** {len(bot.tree.get_commands())} top-level slash commands "
        f"({total_slash} including subcommands) · {total_prefix} prefix/hybrid commands.", "",
        "`slash+prefix` = hybrid command (dono tarah se chalta hai).", "",
    ]
    for cog in sorted(by_cog, key=lambda k: k.lower()):
        rows = sorted(by_cog[cog], key=lambda r: (r[1], r[0]))
        out += [f"## {cog} ({len(rows)})", "", "| Command | Type | Description |", "|---|---|---|"]
        out += [f"| `{n}` | {k} | {d} |" for n, k, d in rows]
        out += [""]
    open("COMMANDS.md", "w").write("\n".join(out) + "\n")
    print(f"wrote COMMANDS.md: {len(entries)} unique commands across {len(by_cog)} cogs")


asyncio.run(main())
