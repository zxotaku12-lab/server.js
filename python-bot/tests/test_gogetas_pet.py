# Credits: gogeta_gg
"""Tests for Gogeta's Pet (friendly-savage persona, custom-emoji-only). No Discord gateway or API keys needed."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _path(name):
    nested = ROOT / "cogs" / name
    return nested if nested.exists() else ROOT / name


SOURCE = _path("gogetas_pet.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _load_helpers():
    """Execute only the pure helpers/constants so tests run without discord installed."""
    wanted = {"looks_like_hinglish", "tidy", "shorten", "gif_query_for", "wants_depth", "addresses_creator"}
    keep = []
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            keep.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id.isupper() and t.id != "AI_ENABLED" for t in node.targets
        ):
            seg = ast.get_source_segment(SOURCE, node) or ""
            if "os.getenv" not in seg and "_flag(" not in seg and "_num(" not in seg:
                keep.append(node)
    ns = {"re": re, "random": __import__("random")}
    exec(compile(ast.Module(keep, []), "gogetas_pet_helpers", "exec"), ns)
    return ns


H = _load_helpers()


class PersonaTests(unittest.TestCase):
    def setUp(self):
        self.p = " ".join(H["PERSONA"].lower().split())

    def test_personality_traits_present(self):
        for phrase in ("friendly-savage", "dark, absurd, deadpan humor", "genuinely smart",
                       "correct, useful answer first", "custom server emoji only", "never unicode emoji"[:0] or "never use unicode emoji"):
            self.assertIn(phrase, self.p)

    def test_creator_and_member_address_rules(self):
        for title in ("dad", "pops", "daddy", "papa", "father"):
            self.assertIn(title, self.p)
        for slang in ("bro", "bruhh", "dude", "blud", "kid"):
            self.assertIn(slang, H["MEMBER_ADDRESSES"])
        for title in ("Pops", "Dad", "Daddy"):
            self.assertIn(title, H["CREATOR_TITLES"])
        self.assertTrue(set(x.lower() for x in H["CREATOR_TITLES"]).isdisjoint(H["MEMBER_ADDRESSES"]))
        self.assertIn("never call the creator bro", self.p)

    def test_no_removed_features_come_back(self):
        code = SOURCE.replace(ast.get_docstring(TREE) or "", "").lower()
        for banned in ("sqlite3", "chaos_ai", "memory_store"):
            self.assertNotIn(banned, code)

    def test_no_hardcoded_unicode_emoji_anywhere_in_source(self):
        self.assertIsNone(re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", SOURCE))
        self.assertNotIn("EMOJI_FALLBACKS", SOURCE)
        self.assertNotIn("plain_greeting_reply", SOURCE)

    def test_fallbacks_are_in_voice_and_emoji_free(self):
        for line in H["FALLBACKS"]:
            self.assertIn("{who}", line)
        self.assertIsNone(re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", " ".join(H["FALLBACKS"])))

    def test_hinglish_detection(self):
        f = H["looks_like_hinglish"]
        self.assertTrue(f("aja dinner krte Sath me Teri mummy ko b le ana"))
        self.assertTrue(f("Mummy to Teri chahiye muje"))
        self.assertFalse(f("Who tf is @Gogeta's pet"))
        self.assertFalse(f("Shut the fuck up"))


class DepthTests(unittest.TestCase):
    def test_real_questions_get_depth_banter_does_not(self):
        d = H["wants_depth"]
        self.assertTrue(d("how do i reverse a list in python"))
        self.assertTrue(d("explain the difference between TCP and UDP please"))
        self.assertFalse(d("fck u"))
        self.assertFalse(d("how are you"))
        self.assertFalse(d("yo"))

    def test_creator_title_detection(self):
        a = H["addresses_creator"]
        self.assertTrue(a("yo pops, what"))
        self.assertTrue(a("Daddy, look at this"))
        self.assertTrue(a("Boss, that was cold"))
        self.assertFalse(a("that was the final boss of bad takes"))
        self.assertFalse(a("nice try, blud"))


class CleanupTests(unittest.TestCase):
    def test_leaked_ids_and_half_tags_removed(self):
        tidy = H["tidy"]
        out = tidy("<:pepe:111111111111111111>222222222222222222 You just muted the wrong gremlin")
        self.assertNotIn("222222222222222222", out)
        self.assertIn("<:pepe:111111111111111111>", out)
        self.assertEqual(tidy("nice try <:ehhe:14094008"), "nice try")

    def test_cut_off_sentence_loses_its_dangling_tail(self):
        self.assertEqual(H["tidy"]("Fine, play rough. But you"), "Fine, play rough.")

    def test_shorten_banter_vs_answers(self):
        s = H["shorten"]
        self.assertEqual(s("One. Two. Three. Four."), "One. Two. Three.")
        self.assertEqual(s("One. Two. Three. Four.", max_lines=8, max_sentences=7, max_chars=1300),
                         "One. Two. Three. Four.")

    def test_gif_queries_follow_the_message(self):
        self.assertIn(H["gif_query_for"]("who tf is this"), ("confused", "who are you", "huh"))


class BoundaryTests(unittest.TestCase):
    def test_ticket_channels_are_a_fail_closed_boundary(self):
        cog = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "GogetasPet")
        method = next(n for n in cog.body if isinstance(n, ast.FunctionDef) and n.name == "_is_ticket_channel")
        body = ast.get_source_segment(SOURCE, method) or ""
        self.assertIn("tickets_db.get_ticket_by_channel", body)
        self.assertIn("return True", body)
        self.assertIn("if self._is_ticket_channel(message.channel):", SOURCE)

    def test_all_replies_go_through_custom_emoji_enforcement(self):
        self.assertIn("return self._finish_emoji(reply, pool, latest_text)[:1900]", SOURCE)
        self.assertIn("self._finish_emoji(reply, self._emoji_pool(guild), latest_text)", SOURCE)
        self.assertIn('UNICODE_EMOJI_RE.sub("", reply)', SOURCE)

    def test_creator_is_verified_by_id_only(self):
        self.assertIn("def _is_creator", SOURCE)
        self.assertNotRegex(SOURCE, r"\b\d{17,20}\b")  # no hardcoded IDs; creator comes from .env

    def test_server_context_is_explicit_and_ticket_boundary_remains_separate(self):
        self.assertIn("load_guild_knowledge", SOURCE)
        self.assertIn("build_server_context", SOURCE)
        self.assertIn("Guild reference notes may be outdated", SOURCE)

    def test_uses_isolated_history_namespace(self):
        self.assertIn('HISTORY_NAMESPACE = "gogetas_pet"', SOURCE)
        self.assertIn("history_namespace=HISTORY_NAMESPACE", SOURCE)


if __name__ == "__main__":
    unittest.main()
