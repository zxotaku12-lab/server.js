# Credits: gogeta_gg
import asyncio, sys, tempfile, shutil, os, traceback
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, AsyncMock
import discord

ROOT = Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
import cogs.automod as am

tmp = Path(tempfile.mkdtemp())
am.DB_PATH = tmp / "automod_test.db"

GID = 123456789012345678

class FakePerms:
    manage_messages = True; moderate_members = True; view_channel = True
    ban_members = True; kick_members = True; manage_roles = True; manage_guild = True; administrator=False

def make_message(content, *, author_id=555, roles=(), bot=False, webhook_id=None, channel_id=900, attachments=(), snapshots=()):
    guild = MagicMock(spec=discord.Guild); guild.id = GID; guild.owner_id = 1
    me = MagicMock(); me.guild_permissions = FakePerms(); guild.me = me
    guild.get_channel.return_value = None
    guild.ban = AsyncMock(); 
    author = MagicMock(spec=discord.Member); author.id = author_id; author.bot = bot
    author.roles = [NS(id=r) for r in roles]; author.timeout = AsyncMock(); author.kick = AsyncMock(); author.add_roles = AsyncMock()
    author.mention = f"<@{author_id}>"; author.guild_permissions = FakePerms()
    channel = MagicMock(); channel.id = channel_id; channel.permissions_for.return_value = FakePerms(); channel.send = AsyncMock()
    m = MagicMock(spec=discord.Message)
    m.guild = guild; m.author = author; m.channel = channel; m.content = content
    m.mentions = []; m.role_mentions = []; m.mention_everyone = False
    m.attachments = list(attachments); m.embeds = []; m.delete = AsyncMock(); m.webhook_id = webhook_id
    m.message_snapshots = list(snapshots)
    m.flags = discord.MessageFlags()
    return m

def make_cog():
    bot = MagicMock(); bot.intents = discord.Intents.default(); bot.intents.message_content = True
    cog = am.Automod(bot)
    cog.db.ensure(GID)
    cog.db.update_settings(GID, enabled=1, default_action="delete")
    return cog

async def run(cog, text, **kw):
    m = make_message(text, **kw)
    sigs = None
    try:
        sigs = cog.detect(m) if not cog.exempt(m) else "EXEMPT"
        if sigs and sigs != "EXEMPT":
            await cog.enforce(m, sigs)
    except Exception:
        print("  !! EXCEPTION in enforce:"); traceback.print_exc(limit=4)
    return m, sigs

async def main():
    cog = make_cog()
    cases = [
        ("plain https link", "check https://evil.example.com/free-nitro"),
        ("bare domain", "go to evil-site.xyz/free now"),
        ("discord invite", "join discord.gg/abcdef"),
        ("zero-width invite", "join discord.gg/\u200babcdef"),
        ("zw in host invite", "join disc\u200bord.gg/abcdef"),
        ("spaced invite", "join discord . gg / abcdef"),
        ("dsc.gg invite", "join dsc.gg/abcdef"),
        ("masked link", "[click](https://evil.example.com)"),
    ]
    for name, text in cases:
        m, sigs = await run(cog, text, author_id=1000+hash(name)%1000)
        print(f"{name:22s} signals={sigs} deleted={m.delete.await_count>0}")
    n = len(cog.db.incidents(GID, 50))
    print("incidents written:", n)

if __name__ == "__main__":
    asyncio.run(main())
