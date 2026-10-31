# Credits: gogeta_gg
"""Router resilience: hedged parallel providers, health-aware cooldowns, never going dark. Offline."""
import asyncio
import importlib
import sys
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if not (ROOT / "cogs").exists():
    raise unittest.SkipTest("cogs/ not found")


def _import_router():
    try:
        import discord, aiohttp  # noqa: F401
    except ImportError:  # offline stubs so the scheduling logic can be tested without Discord
        class _C:
            def __init__(self, *a, **k): ...
        def mod(name, **kw):
            m = types.ModuleType(name); m.__dict__.update(kw); sys.modules[name] = m; return m
        mod("aiohttp", ClientSession=_C, ClientTimeout=_C, ClientError=type("ClientError", (Exception,), {}))
        d = mod("discord", Message=_C)
        mod("discord.ext")
        cmds = mod("discord.ext.commands", Cog=type("Cog", (), {"listener": staticmethod(lambda *a, **k: (lambda f: f))}), Bot=_C)
        sys.modules["discord.ext"].commands = cmds; d.ext = sys.modules["discord.ext"]
    return importlib.import_module("cogs.multi_ai")


M = _import_router()


def make_router(order=("groq", "cerebras", "gemini")):
    M.PROVIDER_ORDER[:] = list(order)
    M.provider_cooldowns.clear()
    M.HEDGE_DELAY = 0.05
    M.ATTEMPT_TIMEOUT = 1.0
    M.TOTAL_TIMEOUT = 5.0
    r = object.__new__(M.MultiAI)
    r.conversations = {}
    r.last_provider = None
    r.provider_stats = {n: {"ok": 0, "errors": 0, "rate_limits": 0} for n in M.PROVIDERS}
    r.health = {n: {"fails": 0, "ewma": None} for n in M.PROVIDERS}
    r.session = types.SimpleNamespace(closed=False)
    r.key_pools = {}
    r._provider_configured = lambda p: True
    return r


def ok(text="hello there"):
    return {"choices": [{"message": {"content": text}}]}


def run(coro):
    return asyncio.run(coro)


async def ask(r, **kw):
    return await r.ask_custom("hi", user=types.SimpleNamespace(id=1), guild=None,
                              channel=types.SimpleNamespace(id=2), system_prompt="x", **kw)


class ResilienceTests(unittest.TestCase):
    def test_hung_provider_is_hedged_so_reply_is_fast(self):
        r = make_router()
        async def req(provider, messages, **kw):
            if provider == "groq":
                await asyncio.sleep(60)          # hangs forever
            return ok(f"from {provider}")
        r._request_provider = req
        t = time.monotonic()
        reply = run(ask(r))
        self.assertEqual(reply, "from cerebras")
        self.assertLess(time.monotonic() - t, 1.0)

    def test_failures_roll_over_to_the_next_provider(self):
        r = make_router()
        async def req(provider, messages, **kw):
            if provider == "groq":
                raise RuntimeError("404: model not found")
            if provider == "cerebras":
                raise RuntimeError("500: boom")
            return ok("third time lucky")
        r._request_provider = req
        self.assertEqual(run(ask(r)), "third time lucky")
        self.assertGreaterEqual(M.provider_cooldowns["groq"] - time.monotonic(), 800)   # wrong model: parked long

    def test_all_cooling_down_still_tries_instead_of_going_dark(self):
        r = make_router()
        for p in M.PROVIDER_ORDER:
            M.provider_cooldowns[p] = time.monotonic() + 100
        async def req(provider, messages, **kw):
            return ok("still here")
        r._request_provider = req
        self.assertEqual(run(ask(r)), "still here")

    def test_everything_down_raises_cleanly(self):
        r = make_router()
        async def req(provider, messages, **kw):
            raise RuntimeError("503: down")
        r._request_provider = req
        with self.assertRaises(RuntimeError):
            run(ask(r))

    def test_empty_reasoning_only_reply_falls_through(self):
        r = make_router()
        async def req(provider, messages, **kw):
            return ok("<think>hmm</think>") if provider == "groq" else ok("real answer")
        r._request_provider = req
        self.assertEqual(run(ask(r)), "real answer")

    def test_reasoning_token_headroom_and_compact_flag(self):
        r = make_router()
        seen = {}
        async def req(provider, messages, **kw):
            seen.update(kw)
            return ok("a\nb\nc\nd\ne")
        r._request_provider = req
        reply = run(ask(r, max_output=160, compact=False))
        self.assertEqual(seen["max_tokens"], 160 + M.TOKEN_HEADROOM)
        self.assertEqual(reply.count("\n"), 4)            # not squashed to 3 lines
        self.assertEqual(run(ask(r, max_output=160, compact=True)).count("\n"), 2)

    def test_provider_diagnostics_never_expose_credentials(self):
        r = make_router()
        report = r.provider_diagnostics()
        self.assertIn("groq", report)
        self.assertIn("configured", report["groq"])
        self.assertIn("average_latency_seconds", report["groq"])
        self.assertNotIn("key-a", str(report).lower())
        self.assertNotIn("api_key", str(report).lower())
        self.assertNotIn("prompt", str(report).lower())

    def test_unhealthy_provider_is_demoted(self):
        r = make_router()
        r.health["groq"]["fails"] = 3
        self.assertEqual(r._ordered_providers()[0], "cerebras")

    def test_losing_requests_are_cancelled(self):
        r = make_router()
        cancelled = []
        async def req(provider, messages, **kw):
            if provider == "groq":
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    cancelled.append(provider); raise
            return ok("fast")
        r._request_provider = req
        run(ask(r))
        self.assertEqual(cancelled, ["groq"])


if __name__ == "__main__":
    unittest.main()
