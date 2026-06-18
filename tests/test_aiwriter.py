import os
import tempfile
import unittest
from pathlib import Path

from blab import aiwriter

FACTS = {
    "category": "hung_piece",
    "your_move_san": "Qd5",
    "best_move_san": "Qd2",
    "pv_san": "Qd2 Rd8",
    "motifs": "hangingPiece",
    "eval_before": "+0.30",
    "eval_after": "-8.70",
    "user_color": "White",
}


class AIWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_cache = aiwriter.CACHE_DIR
        aiwriter.CACHE_DIR = self.tmp
        self._had_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BLAB_AI_PROVIDER", None)

    def tearDown(self) -> None:
        aiwriter.CACHE_DIR = self._orig_cache
        if self._had_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._had_key

    def test_template_note_uses_facts(self) -> None:
        note = aiwriter.template_note(FACTS)
        self.assertIn("Qd5", note)
        self.assertIn("Qd2", note)

    def test_coach_falls_back_to_template_without_key(self) -> None:
        text, source = aiwriter.coach(FACTS)
        self.assertEqual(source, "template")
        self.assertIn("Qd5", text)

    def test_available_reflects_key(self) -> None:
        self.assertFalse(aiwriter.available("anthropic"))
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        try:
            self.assertTrue(aiwriter.available("anthropic"))
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_explain_uses_provider_and_caches(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        calls = []

        def fake(prompt, model):
            calls.append(prompt)
            return "Grounded note."

        original = aiwriter._anthropic
        aiwriter._anthropic = fake
        try:
            first = aiwriter.explain(FACTS)
            second = aiwriter.explain(FACTS)  # served from cache, no second call
        finally:
            aiwriter._anthropic = original
            del os.environ["ANTHROPIC_API_KEY"]

        self.assertEqual(first, "Grounded note.")
        self.assertEqual(second, "Grounded note.")
        self.assertEqual(len(calls), 1)
        text, source = aiwriter.coach(FACTS)
        self.assertEqual(source, "ai")  # cached AI note is reused even after key removed

    def test_prompt_is_grounded(self) -> None:
        prompt = aiwriter._facts_to_prompt(FACTS)
        self.assertIn("Qd5", prompt)
        self.assertIn("only these facts", prompt)


if __name__ == "__main__":
    unittest.main()
