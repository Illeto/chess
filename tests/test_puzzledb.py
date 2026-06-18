import tempfile
import unittest
from pathlib import Path

from blab import puzzledb

FEN = "4k3/8/8/8/8/8/4q3/4K2R b - - 0 1"
# Lichess layout: [id, fen, moves, rating, rd, pop, plays, themes, url, openings]
ROW_MATCH = ["pz1", FEN, "e2c4 h1h8", "800", "75", "90", "1000", "hangingPiece fork", "https://lichess.org/x", ""]
ROW_RATING = ["pz2", FEN, "e2c4 h1h8", "2000", "75", "90", "1000", "fork", "u", ""]
ROW_THEME = ["pz3", FEN, "e2c4 h1h8", "800", "75", "90", "1000", "endgame", "u", ""]


class PuzzleDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Path(tempfile.mkdtemp()) / "p.sqlite"

    def test_build_filters_then_query(self) -> None:
        kept = puzzledb.build_from_rows(self.db, [ROW_MATCH, ROW_RATING, ROW_THEME])
        self.assertEqual(kept, 1)  # rating and theme filters drop the other two
        self.assertTrue(puzzledb.available(self.db))

        res = puzzledb.query(["fork"], limit=5, db_path=self.db)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["puzzle_id"], "pz1")
        self.assertEqual(res[0]["side"], "white")   # white to move after black's setup move
        self.assertEqual(res[0]["best_uci"], "h1h8")

        got = puzzledb.get("pz1", db_path=self.db)
        self.assertEqual(got["fen"], res[0]["fen"])
        self.assertEqual(puzzledb.query(["pin"], limit=5, db_path=self.db), [])

    def test_query_missing_db_is_empty(self) -> None:
        self.assertEqual(
            puzzledb.query(["fork"], 5, db_path=Path("/nonexistent/x.sqlite")), []
        )
        self.assertFalse(puzzledb.available(Path("/nonexistent/x.sqlite")))


if __name__ == "__main__":
    unittest.main()
