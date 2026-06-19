import shutil
import tempfile
import unittest
from pathlib import Path

import chess

import blunder_lab as lab

try:
    import flask  # noqa: F401

    from web import engine_pool
    from web.app import create_app

    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False


def mate_in_one_finding() -> lab.MoveFinding:
    """A deterministic fixture: White to move has Ra8# (best); Kg1 throws it."""
    return lab.MoveFinding(
        kind="blunder",
        game_index=1,
        game_date="2026-01-01",
        time_class="rapid",
        url="https://example.com/game/1",
        event="Test",
        white="tester",
        black="opponent",
        user_color="White",
        ply=1,
        move_number=1,
        fen="6k1/5ppp/8/8/8/8/8/R6K w - - 0 1",
        your_move_san="Kg1",
        your_move_uci="h1g1",
        best_move_san="Ra8#",
        best_move_uci="a1a8",
        loss_cp=100000,
        eval_before_cp=100000,
        eval_after_cp=0,
        eval_before="M+1",
        eval_after="0.00",
        pv_san="Ra8#",
        pv_uci="a1a8",
        theme="mate",
    )


@unittest.skipUnless(HAVE_FLASK, "Flask (requirements-web.txt) not installed")
class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.run_id = "test_user_20260101_000000"
        run_dir = self.tmp / self.run_id
        run_dir.mkdir()
        finding = mate_in_one_finding()
        lab.write_findings_csv([finding], run_dir / "blunders.csv")
        lab.write_findings_csv([finding], run_dir / "puzzles.csv")

        self._orig_roots = lab.analysis_roots
        lab.analysis_roots = lambda root=Path("analysis"): [self.tmp]

        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        engine_pool.close()
        lab.analysis_roots = self._orig_roots
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_index_renders_without_engine_or_network(self) -> None:
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_engine_status_shape(self) -> None:
        body = self.client.get("/api/engine").get_json()
        self.assertIn("ready", body)

    def test_runs_lists_fixture(self) -> None:
        runs = self.client.get("/api/runs").get_json()["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["id"], self.run_id)
        self.assertEqual(runs[0]["username"], "test_user")

    def test_analyze_requires_username(self) -> None:
        self.assertEqual(self.client.post("/api/analyze", json={}).status_code, 400)

    def test_analyze_rejects_invalid_params(self) -> None:
        bad_payloads = [
            {"username": "../bad"},
            {"username": "tester", "months": 0},
            {"username": "tester", "months": 25},
            {"username": "tester", "max_games": 0},
            {"username": "tester", "max_games": 501},
            {"username": "tester", "depth": 3},
            {"username": "tester", "depth": 21},
            {"username": "tester", "time_class": "classical"},
            {"username": "tester", "months": "abc"},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/api/analyze", json=payload).status_code, 400)

    def test_findings_and_detail(self) -> None:
        listing = self.client.get(f"/api/runs/{self.run_id}/findings").get_json()
        self.assertEqual(listing["count"], 1)
        detail = self.client.get(f"/api/runs/{self.run_id}/findings/0").get_json()
        self.assertEqual(detail["best_move_san"], "Ra8#")
        self.assertTrue(detail["svg"].startswith("<svg"))

    def test_profile_endpoint(self) -> None:
        body = self.client.get(f"/api/runs/{self.run_id}/profile").get_json()
        prof = body["profile"]
        self.assertEqual(len(prof), 1)
        self.assertEqual(prof[0]["count"], 1)
        self.assertIn("due_total", body)
        self.assertIn("progress", prof[0])  # spaced-repetition fields attached
        self.assertEqual(self.client.get(f"/run/{self.run_id}/profile").status_code, 200)

    def test_progress_endpoint(self) -> None:
        body = self.client.get(f"/api/runs/{self.run_id}/progress").get_json()
        self.assertIn("category", body)

    def test_db_puzzle_endpoints(self) -> None:
        from blab import puzzledb

        db = Path(tempfile.mkdtemp()) / "p.sqlite"
        puzzledb.build_from_rows(
            db,
            [["dbz", "4k3/8/8/8/8/8/4q3/4K2R b - - 0 1", "e2c4 h1h8", "800", "0", "0", "0", "fork", "u", ""]],
        )
        original = puzzledb.default_db_path
        puzzledb.default_db_path = lambda: db
        try:
            legal = self.client.get("/api/db/puzzles/dbz/legal").get_json()
            self.assertEqual(legal["side"], "white")
            self.assertIn("h1h8", legal["legal"])
            self.assertEqual(self.client.get("/api/db/puzzles/missing/legal").status_code, 404)
        finally:
            puzzledb.default_db_path = original

    def test_line_endpoint(self) -> None:
        line = self.client.get(f"/api/runs/{self.run_id}/puzzles/0/line").get_json()
        self.assertTrue(line["start_fen"])
        self.assertEqual(line["steps"][0]["san"], "Ra8#")

    def test_lesson_endpoint(self) -> None:
        self.assertEqual(
            self.client.get(f"/api/runs/{self.run_id}/lessons/not_a_category").status_code,
            404,
        )
        lesson = self.client.get(
            f"/api/runs/{self.run_id}/lessons/positional_other"
        ).get_json()
        self.assertIn("concept", lesson)
        self.assertIn("fix", lesson["concept"])
        self.assertEqual(lesson["count"], 1)

    def test_legal_is_puzzle_scoped(self) -> None:
        legal = self.client.get(f"/api/runs/{self.run_id}/puzzles/0/legal").get_json()
        self.assertEqual(legal["side"], "white")
        self.assertIn("a1a8", legal["legal"])

    def test_piece_svg_endpoint(self) -> None:
        ok = self.client.get("/api/piece/N")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.mimetype, "image/svg+xml")
        self.assertTrue(ok.get_data(as_text=True).startswith("<svg"))
        self.assertEqual(self.client.get("/api/piece/x").status_code, 404)
        self.assertEqual(self.client.get("/api/piece/NN").status_code, 404)

    def test_run_id_path_traversal_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/runs/unknownrun/findings").status_code, 404)
        self.assertEqual(self.client.get("/api/runs/..%2f..%2fetc/findings").status_code, 404)

    @unittest.skipUnless(HAVE_FLASK and engine_pool.ready(), "Stockfish not available")
    def test_grade_correct_and_incorrect(self) -> None:
        good = self.client.post(
            f"/api/runs/{self.run_id}/puzzles/0/grade", json={"move": "a1a8"}
        ).get_json()
        self.assertTrue(good["correct"])

        bad = self.client.post(
            f"/api/runs/{self.run_id}/puzzles/0/grade", json={"move": "h1g1"}
        ).get_json()
        self.assertFalse(bad["correct"])

        illegal = self.client.post(
            f"/api/runs/{self.run_id}/puzzles/0/grade", json={"move": "z9z9"}
        )
        self.assertEqual(illegal.status_code, 400)


if __name__ == "__main__":
    unittest.main()
