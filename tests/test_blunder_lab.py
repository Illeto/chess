import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

import chess

import blunder_lab as lab


def make_finding(
    *,
    kind: str = "blunder",
    game_index: int = 1,
    theme: str = "capture, check",
    loss_cp: int = 300,
) -> lab.MoveFinding:
    return lab.MoveFinding(
        kind=kind,
        game_index=game_index,
        game_date="2026-06-16",
        time_class="rapid",
        url=f"https://example.com/game/{game_index}",
        event="Test",
        white="player",
        black=f"opponent-{game_index}",
        user_color="White",
        ply=12,
        move_number=6,
        fen=chess.STARTING_FEN,
        your_move_san="e4",
        your_move_uci="e2e4",
        best_move_san="Nf3",
        best_move_uci="g1f3",
        loss_cp=loss_cp,
        eval_before_cp=100,
        eval_after_cp=-200,
        eval_before="+1.00",
        eval_after="-2.00",
        pv_san="Nf3",
        pv_uci="g1f3",
        theme=theme,
    )


class BlunderLabTests(unittest.TestCase):
    def test_parse_move_accepts_san_and_uci(self) -> None:
        board = chess.Board()

        self.assertEqual(lab.parse_move(board, "e4"), chess.Move.from_uci("e2e4"))
        self.assertEqual(lab.parse_move(board, "g1f3"), chess.Move.from_uci("g1f3"))
        self.assertIsNone(lab.parse_move(board, "e5"))

    def test_terminal_score_handles_mate_and_draw(self) -> None:
        board = chess.Board()
        for san in ["f3", "e5", "g4", "Qh4#"]:
            board.push_san(san)

        self.assertEqual(lab.terminal_score(board, chess.BLACK), (lab.MATE_SCORE, "M+0"))
        self.assertEqual(lab.terminal_score(board, chess.WHITE), (-lab.MATE_SCORE, "M-0"))

        stalemate = chess.Board("7k/5Q2/7K/8/8/8/8/8 b - - 0 1")
        self.assertEqual(lab.terminal_score(stalemate, chess.WHITE), (0, "draw"))
        self.assertEqual(lab.terminal_score(stalemate, chess.BLACK), (0, "draw"))

    def test_render_board_orients_for_both_sides(self) -> None:
        board = chess.Board()

        white_lines = lab.render_board(board, chess.WHITE).splitlines()
        self.assertEqual(white_lines[0], "8 r n b q k b n r")
        self.assertEqual(white_lines[-1], "  a b c d e f g h")

        black_lines = lab.render_board(board, chess.BLACK).splitlines()
        self.assertEqual(black_lines[0], "1 R N B K Q B N R")
        self.assertEqual(black_lines[-1], "  h g f e d c b a")

    def test_safe_extract_tar_rejects_path_traversal(self) -> None:
        data = b"bad"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            member = tarfile.TarInfo("../evil.txt")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        buffer.seek(0)

        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(fileobj=buffer) as archive:
                with self.assertRaises(lab.UserFacingError):
                    lab.safe_extract_tar(archive, Path(tmp))

    def test_safe_extract_zip_rejects_path_traversal(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("../evil.txt", "bad")
        buffer.seek(0)

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(buffer) as archive:
                with self.assertRaises(lab.UserFacingError):
                    lab.safe_extract_zip(archive, Path(tmp))

    def test_study_focus_summarizes_themes_and_games(self) -> None:
        findings = [
            make_finding(game_index=1, kind="blunder", theme="capture, check"),
            make_finding(game_index=1, kind="mistake", theme="capture"),
            make_finding(game_index=2, kind="inaccuracy", theme="best move"),
        ]
        settings = lab.AnalysisSettings(
            username="player",
            engine_path=Path("stockfish"),
            depth=10,
            movetime_ms=None,
            threads=None,
            hash_mb=None,
            skip_opening_plies=8,
            inaccuracy_cp=75,
            mistake_cp=150,
            blunder_cp=300,
            puzzle_min_loss_cp=150,
            puzzle_min_eval_cp=-50,
            max_pv_moves=6,
        )

        lines = lab.study_focus_lines(findings, findings[:1], settings)
        text = "\n".join(lines)

        self.assertIn("Most repeated themes: capture (2)", text)
        self.assertIn("2026-06-16 player vs opponent-1", text)
        self.assertIn("2 finding(s), 1 blunder(s), 1 puzzle(s)", text)


if __name__ == "__main__":
    unittest.main()
