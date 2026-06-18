import tempfile
import unittest
from pathlib import Path

from blab import puzzledb
from blab.classify import CATEGORIES
from blab.lessons import CATEGORY_CONCEPTS, build_lesson

NO_DB = Path("/nonexistent/puzzles.sqlite")
FORK_ROW = ["pz1", "4k3/8/8/8/8/8/4q3/4K2R b - - 0 1", "e2c4 h1h8", "800", "75", "90", "1000", "fork", "u", ""]


class LessonTests(unittest.TestCase):
    def test_own_drills_filtered_by_category(self):
        rows = [
            {"category": "hung_piece"},
            {"category": "allowed_fork"},
            {"category": "hung_piece"},
            {"category": ""},
        ]
        lesson = build_lesson("hung_piece", rows, db_path=NO_DB)
        own = [d["ref"] for d in lesson["drills"] if d["source"] == "own"]
        self.assertEqual(own, [0, 2])
        self.assertEqual(lesson["own_count"], 2)
        self.assertEqual(lesson["db_count"], 0)
        self.assertEqual(lesson["label"], "Hung a piece")
        self.assertIn("fix", lesson["concept"])

    def test_db_topup_when_few_own(self):
        db = Path(tempfile.mkdtemp()) / "p.sqlite"
        puzzledb.build_from_rows(db, [FORK_ROW])
        lesson = build_lesson("allowed_fork", [], db_path=db, target=3)
        self.assertEqual(lesson["own_count"], 0)
        self.assertGreaterEqual(lesson["db_count"], 1)
        self.assertEqual(lesson["drills"][0]["source"], "db")
        self.assertEqual(lesson["drills"][0]["ref"], "pz1")

    def test_every_category_has_a_concept(self):
        for category in CATEGORIES:
            self.assertIn(category, CATEGORY_CONCEPTS)
            self.assertTrue(CATEGORY_CONCEPTS[category]["fix"])


if __name__ == "__main__":
    unittest.main()
