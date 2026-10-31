# Credits: gogeta_gg
"""Offline tests for scoped guild knowledge and runtime context."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cogs.server_knowledge import build_server_context, load_guild_knowledge


class GuildKnowledgeTests(unittest.TestCase):
    def test_loads_only_the_requested_numeric_guild_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "12345.md").write_text("Premium access: use /verify.", encoding="utf-8")
            (root / "67890.md").write_text("Other server secret", encoding="utf-8")
            self.assertEqual(load_guild_knowledge(12345, root=root), "Premium access: use /verify.")
            self.assertNotIn("Other server secret", load_guild_knowledge(12345, root=root))

    def test_missing_or_invalid_guild_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(load_guild_knowledge("../123", root=td), "")
            self.assertEqual(load_guild_knowledge(12345, root=td), "")

    def test_content_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "123.md").write_text("x" * 2000, encoding="utf-8")
            self.assertLessEqual(len(load_guild_knowledge(123, root=root, max_bytes=300)), 300)

    def test_context_contains_bounded_metadata_and_roles(self):
        guild = SimpleNamespace(name="Test Guild", description="Official info")
        channel = SimpleNamespace(name="help", topic="Ask support here")
        author = SimpleNamespace(roles=[SimpleNamespace(name="@everyone"), SimpleNamespace(name="Member")])
        context = build_server_context(guild, channel, author, knowledge="Use /verify for access")
        for expected in ("Test Guild", "Official info", "help", "Ask support here", "Member", "/verify"):
            self.assertIn(expected, context)
        self.assertNotIn("@everyone", context)

    def test_symlinked_guild_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "67890.md").write_text("Other server secret", encoding="utf-8")
            try:
                (root / "12345.md").symlink_to(root / "67890.md")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this platform")
            self.assertEqual(load_guild_knowledge(12345, root=root), "")

    def test_only_ascii_decimal_guild_ids_are_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "123.md").write_text("valid", encoding="utf-8")
            self.assertEqual(load_guild_knowledge("１２３", root=root), "")
            self.assertEqual(load_guild_knowledge("../123", root=root), "")
            self.assertEqual(load_guild_knowledge("1" * 21, root=root), "")

    def test_non_regular_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "123.md").mkdir()
            self.assertEqual(load_guild_knowledge(123, root=root), "")

    def test_invalid_limit_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "123.md").write_text("x" * 500, encoding="utf-8")
            self.assertLessEqual(len(load_guild_knowledge(123, root=root, max_bytes="invalid")), 6000)


if __name__ == "__main__":
    unittest.main()
