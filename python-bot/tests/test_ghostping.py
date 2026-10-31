# Credits: gogeta_gg
"""Ghost-ping-on-join tests. Offline: Discord objects are faked."""
import asyncio
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _import():
    try:
        import discord  # noqa: F401
    except ImportError:  # stubs so the logic is testable without discord.py installed
        def mod(name, **kw):
            m = types.ModuleType(name); m.__dict__.update(kw); sys.modules[name] = m; return m

        class AllowedMentions:
            def __init__(self, **kw): self.kw = kw
            @classmethod
            def none(cls): return cls()

        class _Cog:
            @staticmethod
            def listener(*a, **k): return lambda f: f

        passthrough = lambda *a, **k: (lambda f: f)  # noqa: E731

        class _Group:
            def __init__(self, f): self.f = f
            def command(self, *a, **k): return passthrough()
            def __call__(self, *a, **k): return self.f(*a, **k)

        d = mod("discord", TextChannel=type("TextChannel", (), {"permissions_for": lambda self, me: None, "send": None, "id": 0, "name": "", "mention": ""}), Member=type("Member", (), {}),
                Guild=type("Guild", (), {}), Message=type("Message", (), {}), AllowedMentions=AllowedMentions,
                NotFound=type("NotFound", (Exception,), {}), Forbidden=type("Forbidden", (Exception,), {}),
                HTTPException=type("HTTPException", (Exception,), {}))
        mod("discord.app_commands", describe=passthrough)
        d.app_commands = sys.modules["discord.app_commands"]
        mod("discord.ext")
        cmds = mod("discord.ext.commands", Cog=_Cog, Bot=object, Context=object, guild_only=passthrough,
                   has_permissions=passthrough,
                   hybrid_command=passthrough)
        sys.modules["discord.ext"].commands = cmds
        d.ext = sys.modules["discord.ext"]
    return importlib.import_module("cogs.ghostping")


G = _import()
import discord  # noqa: E402  (real or stub)


def fake_channel(cid, name, can_send=True):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id, ch.name, ch.mention = cid, name, f"<#{cid}>"
    ch.permissions_for.return_value = types.SimpleNamespace(view_channel=can_send, send_messages=can_send)
    msg = MagicMock()
    msg.delete = AsyncMock()
    ch.send = AsyncMock(return_value=msg)
    ch._msg = msg
    return ch


def fake_guild(channels, members=()):
    by_id = {c.id: c for c in channels}
    member_ids = {m.id: m for m in members}
    return types.SimpleNamespace(
        id=1, me=object(), text_channels=list(channels),
        get_channel=by_id.get, get_member=member_ids.get,
    )


def fake_member(guild_holder, uid=5, pending=False):
    m = types.SimpleNamespace(id=uid, bot=False, pending=pending, mention=f"<@{uid}>", guild=None)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        G.setup_database()
        G.SEND_GAP = 0
        G.DELETE_DELAY = 0
        self.cog = G.GhostPing(MagicMock())

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()


class ParsingTests(unittest.TestCase):
    def test_mentions_ids_names_dupes_and_unknowns(self):
        rules, info = fake_channel(111111111111111111, "rules"), fake_channel(222222222222222222, "info")
        by_id = {c.id: c for c in (rules, info)}
        names = {c.name: c for c in (rules, info)}
        is_text = lambda c: isinstance(c, discord.TextChannel)  # noqa: E731
        found, unknown = G.parse_channels(
            "<#111111111111111111>, 222222222222222222 #rules info nope 999999999999999999",
            by_id.get, names.get, is_text)
        self.assertEqual(found, [111111111111111111, 222222222222222222])
        self.assertEqual(unknown, ["nope", "999999999999999999"])

    def test_non_text_channel_is_rejected(self):
        voice = types.SimpleNamespace(id=333333333333333333)
        found, unknown = G.parse_channels("<#333333333333333333>", {333333333333333333: voice}.get,
                                          lambda n: None, lambda c: isinstance(c, discord.TextChannel))
        self.assertEqual((found, unknown), ([], ["<#333333333333333333>"]))


class StorageTests(Base):
    def test_set_replaces_and_dedups_in_order(self):
        self.assertEqual(G.get_channels(1), [])
        G.save_channels(1, [30, 10, 30, 20])
        self.assertEqual(G.get_channels(1), [30, 10, 20])
        G.save_channels(1, [5])
        self.assertEqual(G.get_channels(1), [5])

    def test_cap_clear_and_guild_isolation(self):
        self.assertEqual(len(G.save_channels(1, range(1, 100))), G.MAX_CHANNELS)
        G.save_channels(2, [9])
        G.save_channels(1, [])
        self.assertEqual((G.get_channels(1), G.get_channels(2)), ([], [9]))


class PingTests(Base):
    def _setup(self, **chan_kw):
        a, b, c = fake_channel(11, "rules"), fake_channel(12, "info"), fake_channel(13, "roles", **chan_kw)
        member = fake_member(None)
        guild = fake_guild([a, b, c], members=[member])
        member.guild = guild
        G.save_channels(1, [11, 12, 13])
        return a, b, c, member

    def test_pings_every_channel_with_only_that_user_allowed_then_deletes(self):
        a, b, c, member = self._setup()
        async def go():
            sent, failed = await self.cog._ping_member(member)
            await asyncio.sleep(0.05)
            return sent, failed
        sent, failed = asyncio.run(go())
        self.assertEqual((sent, failed), (3, []))
        for ch in (a, b, c):
            args, kwargs = ch.send.call_args
            self.assertEqual(args[0], "<@5>")
            self.assertNotIn("silent", kwargs)                 # silent would suppress the notification
            ch._msg.delete.assert_awaited()

    def test_channel_without_permission_is_skipped_and_reported(self):
        a, b, c, member = self._setup(can_send=False)
        sent, failed = asyncio.run(self.cog._ping_member(member))
        self.assertEqual((sent, failed), (2, ["<#13>"]))
        c.send.assert_not_awaited()

    def test_no_channels_or_departed_member_sends_nothing(self):
        a, b, c, member = self._setup()
        member.guild.get_member = lambda i: None                                          # left already
        self.assertEqual(asyncio.run(self.cog._ping_member(member)), (0, []))
        member.guild.get_member = lambda i: member
        G.save_channels(1, [])
        self.assertEqual(asyncio.run(self.cog._ping_member(member)), (0, []))

    def test_send_failure_in_one_channel_does_not_stop_the_rest(self):
        a, b, c, member = self._setup()
        b.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "no"))
        sent, failed = asyncio.run(self.cog._ping_member(member))
        self.assertEqual((sent, failed), (2, ["<#12>"]))


class JoinFlowTests(Base):
    def test_join_queue_pings_each_new_member_once(self):
        a = fake_channel(11, "rules")
        members = [fake_member(None, uid=100 + i) for i in range(3)]
        guild = fake_guild([a], members=members)
        for m in members: m.guild = guild
        G.save_channels(1, [11])
        async def go():
            for m in members:
                await self.cog.on_member_join(m)
            await asyncio.sleep(0.3)
            await self.cog.cog_unload()
        asyncio.run(go())
        self.assertEqual([c.args[0] for c in a.send.call_args_list], ["<@100>", "<@101>", "<@102>"])

    def test_bots_ignored_and_screening_members_wait_until_they_pass(self):
        a = fake_channel(11, "rules")
        human, bot_user = fake_member(None, uid=7, pending=True), fake_member(None, uid=8)
        bot_user.bot = True
        guild = fake_guild([a], members=[human, bot_user])
        human.guild = bot_user.guild = guild
        G.save_channels(1, [11])
        async def go():
            await self.cog.on_member_join(bot_user)
            await self.cog.on_member_join(human)
            await asyncio.sleep(0.1)
            before_sent = a.send.await_count
            human.pending = False
            await self.cog.on_member_update(human, human)
            await asyncio.sleep(0.2)
            await self.cog.cog_unload()
            return before_sent
        before_sent = asyncio.run(go())
        self.assertEqual(before_sent, 0)
        self.assertEqual([c.args[0] for c in a.send.call_args_list], ["<@7>"])

    def test_nothing_queued_when_server_has_no_channels(self):
        member = fake_member(None); member.guild = fake_guild([], members=[member])
        asyncio.run(self.cog.on_member_join(member))
        self.assertEqual(self.cog.queues, {})



A, B = 111111111111111111, 222222222222222222


class CommandTests(Base):
    """The single /ghostping command."""
    def _run(self, channels, chans=None, *, allowed=True):
        chans = chans or [fake_channel(A, "rules", can_send=allowed), fake_channel(B, "info", can_send=allowed)]
        guild = fake_guild(chans)
        ctx = types.SimpleNamespace(guild=guild, send=AsyncMock())
        fn = getattr(G.GhostPing.ghostping, "callback", G.GhostPing.ghostping)
        asyncio.run(fn(self.cog, ctx, channels=channels))
        return ctx.send.call_args.args[0]

    def test_no_argument_shows_state(self):
        self.assertIn("off", self._run(""))
        G.save_channels(1, [A, B])
        self.assertIn(f"<#{A}> <#{B}>", self._run(""))

    def test_one_call_sets_many_channels(self):
        msg = self._run(f"#rules, <#{B}> nope")
        self.assertEqual(G.get_channels(1), [A, B])
        self.assertIn("2/", msg); self.assertIn("nope", msg)

    def test_off_clears(self):
        G.save_channels(1, [A])
        self._run("off")
        self.assertEqual(G.get_channels(1), [])

    def test_nothing_valid_changes_nothing(self):
        G.save_channels(1, [A])
        self.assertIn("at least one", self._run("nope nada"))
        self.assertEqual(G.get_channels(1), [A])

    def test_warns_when_bot_cannot_send(self):
        self.assertIn("can't send", self._run("rules info", allowed=False))


if __name__ == "__main__":
    unittest.main()
