import tempfile
import unittest
from pathlib import Path

from blab import progress


class ProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Path(tempfile.mkdtemp()) / "p.db"
        self.t0 = 1_000_000.0

    def rec(self, correct, fen="A", best="a1a2", cat="hung_piece", now=None):
        return progress.record_attempt(
            "u", fen, best, cat, correct, db_path=self.db, now=now or self.t0
        )

    def test_correct_progression_and_mastery(self) -> None:
        s1 = self.rec(True)
        self.assertEqual(s1["reps"], 1)
        self.assertFalse(s1["mastered"])
        s2 = self.rec(True)
        self.assertEqual(s2["reps"], 2)
        self.assertTrue(s2["mastered"])
        self.assertGreater(s2["due"], self.t0 + 86400)  # pushed days out

    def test_wrong_resets_and_comes_due_soon(self) -> None:
        self.rec(True)
        self.rec(True)
        s = self.rec(False)
        self.assertEqual(s["reps"], 0)
        self.assertLessEqual(s["due"] - self.t0, progress.RELEARN_SECONDS)

    def test_category_progress_counts(self) -> None:
        self.rec(True, fen="A")   # puzzle A, reps 1
        self.rec(True, fen="A")   # A again -> mastered
        self.rec(False, fen="B")  # puzzle B, wrong -> due soon
        cp = progress.category_progress("u", db_path=self.db, now=self.t0 + 700)
        hp = cp["hung_piece"]
        self.assertEqual(hp["seen"], 2)
        self.assertEqual(hp["mastered"], 1)
        self.assertEqual(hp["due"], 1)        # B is due, A is not
        self.assertEqual(hp["attempts"], 3)

    def test_due_keys_respects_schedule(self) -> None:
        self.rec(True, fen="A")   # due ~1 day out
        self.rec(False, fen="B")  # due ~10 min out
        self.assertEqual(progress.due_keys("u", db_path=self.db, now=self.t0), set())
        later = progress.due_keys("u", db_path=self.db, now=self.t0 + 700)
        self.assertIn(progress.puzzle_key("B", "a1a2"), later)
        self.assertNotIn(progress.puzzle_key("A", "a1a2"), later)


if __name__ == "__main__":
    unittest.main()
