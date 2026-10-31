# Credits: gogeta_gg
"""Regression checks for the public chatbot / private-ticket assistant boundary."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _path(name):
    """Works whether the files sit in ROOT/cogs/ or directly in ROOT."""
    nested = ROOT / "cogs" / name
    return nested if nested.exists() else ROOT / name


class SourceBoundaryTests(unittest.TestCase):
    def test_public_chatbot_has_new_identity_and_isolated_history_namespace(self):
        source = (_path("gogetas_pet.py")).read_text(encoding="utf-8")
        self.assertIn("class GogetasPet", source)
        self.assertIn('HISTORY_NAMESPACE = "gogetas_pet"', source)
        self.assertIn("[VERIFIED CREATOR]", source)
        self.assertNotIn("class ChaosAI", source)
        self.assertFalse((_path("chaos_ai.py")).exists())

    def test_ticketai_keeps_ticket_persona_and_uses_distinct_history(self):
        source = (_path("ticket_ai.py")).read_text(encoding="utf-8")
        self.assertIn("first-line support assistant", source)
        self.assertIn("STRICT FIELD BOUNDARY", source)
        self.assertIn('history_namespace="ticket"', source)
        self.assertIn("Do not become a general-purpose chatbot", source)
        self.assertIn("Gogeta's Pet", source)
        self.assertNotIn("Chaos AI", source)

    def test_ticket_database_is_a_hard_boundary_for_public_chat(self):
        # Inspecting the method AST avoids requiring a Discord gateway or API keys.
        source = (_path("gogetas_pet.py")).read_text(encoding="utf-8")
        tree = ast.parse(source)
        cog = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GogetasPet")
        method = next(node for node in cog.body if isinstance(node, ast.FunctionDef) and node.name == "_is_ticket_channel")
        method_src = ast.get_source_segment(source, method) or ""
        self.assertIn("tickets_db.get_ticket_by_channel", method_src)
        self.assertIn("return True", method_src)  # fail closed on DB error
        self.assertIn('if self._is_ticket_channel(message.channel):', source)

    def test_ticket_and_public_histories_have_different_namespaces(self):
        # This contract is implemented by the shared router and is used by both assistants.
        source = (_path("multi_ai.py")).read_text(encoding="utf-8")
        self.assertIn("def _history_key(self, user, channel, namespace: str = \"chat\")", source)
        self.assertIn("namespace=history_namespace", source)
        ticket_source = (_path("ticket_ai.py")).read_text(encoding="utf-8")
        public_source = (_path("gogetas_pet.py")).read_text(encoding="utf-8")
        self.assertIn('history_namespace="ticket"', ticket_source)
        self.assertIn('HISTORY_NAMESPACE = "gogetas_pet"', public_source)

    def test_only_the_new_public_chatbot_registers_hybrid_ai_command(self):
        source = (_path("gogetas_pet.py")).read_text(encoding="utf-8")
        tree = ast.parse(source)
        command_names = []
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for fn in (n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
                decorators = " ".join(ast.get_source_segment(source, d) or "" for d in fn.decorator_list)
                if "hybrid_command" in decorators:
                    command_names.append(fn.name)
        self.assertEqual(command_names, ["ai"])


if __name__ == "__main__":
    unittest.main()
