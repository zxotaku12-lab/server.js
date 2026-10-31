# Credits: gogeta_gg
"""Regression tests for the ChaosAI/MultiAI conversation boundary.

MultiAI is the provider/router layer only: `ask_custom()` is the single entry
point (used by Gogeta's Pet for public chat and by TicketAI for ticket
support), and this cog must never generate a second reply for a human message.
The old public `ask()` method was folded into `ask_custom()` when the ChaosAI
cog became the sole owner of natural-language messages, so these tests target
the current contract.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cogs import multi_ai as multi_ai_module
from cogs.multi_ai import MultiAI


class _FakeSession:
    closed = False


class ChaosConversationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def make_router(self):
        router = MultiAI.__new__(MultiAI)
        router.bot = SimpleNamespace(user=SimpleNamespace(id=999))
        router.session = _FakeSession()
        router.conversations = {}
        router.cooldowns = {}
        router.gif_cooldowns = {}
        router.health = {}
        router.creator_user_id = "123"
        router.creator_name = "Gogeta"
        router.system_prompt = "BASE PERSONALITY"
        router.last_provider = None
        router.provider_stats = {"openai": {"ok": 0, "errors": 0, "rate_limits": 0}}
        router._emoji_system_prompt = self._emoji_system_prompt
        router._provider_configured = lambda provider: provider == "openai"
        router._provider_available = lambda provider: True
        router._apply_custom_emojis = self._apply_custom_emojis
        return router

    async def _emoji_system_prompt(self, guild):
        return "BASE PERSONALITY"

    async def _apply_custom_emojis(self, text, guild, *, ensure_one=True):
        return text

    async def test_chaos_policy_and_output_budget_reach_provider(self):
        router = self.make_router()
        captured = {}

        async def fake_request(provider, messages, *, max_tokens=None, **kwargs):
            captured["provider"] = provider
            captured["messages"] = messages
            captured["max_tokens"] = max_tokens
            return {"choices": [{"message": {"content": "Just lurking in the digital bushes."}}]}

        router._request_provider = fake_request
        user = SimpleNamespace(id=123, display_name="Gogeta")
        guild = SimpleNamespace(id=1, name="Test Server")

        with patch.object(multi_ai_module, "PROVIDER_ORDER", ["openai"]):
            reply = await router.ask_custom(
                "yo pops, what?",
                user=user,
                guild=guild,
                channel=None,
                system_prompt="BASE PERSONALITY\n\nUse the Chaos Gremlin style; keep continuity.",
                max_output=850,
                compact=False,
            )

        self.assertEqual(captured["provider"], "openai")
        # A chat output cap is not a reasoning cap: the router adds headroom so
        # reasoning models can't burn the whole budget thinking and answer "".
        self.assertEqual(captured["max_tokens"], 850 + multi_ai_module.TOKEN_HEADROOM)
        system_message = captured["messages"][0]
        self.assertEqual(system_message["role"], "system")
        self.assertIn("Chaos Gremlin", system_message["content"])
        self.assertEqual(reply, "Just lurking in the digital bushes.")
        self.assertFalse(reply.startswith(("Dad,", "Daddy,", "Pops,", "Papa,")))
        self.assertEqual(router.provider_stats["openai"]["ok"], 1)

    async def test_multi_ai_listener_does_not_generate_a_second_human_reply(self):
        router = self.make_router()
        # Any non-bot message must be left to ChaosAI's single conversation listener.
        message = SimpleNamespace(author=SimpleNamespace(bot=False))
        with patch.object(router, "ask_custom", new=unittest.mock.AsyncMock()) as ask_mock:
            await MultiAI.on_message(router, message)
            ask_mock.assert_not_awaited()

    async def test_multi_ai_listener_only_handles_bot_messages(self):
        """Bot-authored traffic is the only thing on_message may touch (Quest hints)."""
        router = self.make_router()
        handled = []

        async def fake_hint(message):
            handled.append(message)
            return True

        router._handle_quest_access_hint = fake_hint
        bot_message = SimpleNamespace(author=SimpleNamespace(bot=True))

        with patch.object(multi_ai_module, "QUEST_ACCESS_REMINDER_ENABLED", True):
            await MultiAI.on_message(router, bot_message)

        self.assertEqual(handled, [bot_message])


if __name__ == "__main__":
    unittest.main()
