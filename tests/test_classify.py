import unittest

import chess

from blab import classify


def uci(s: str) -> chess.Move:
    return chess.Move.from_uci(s)


class HelperTests(unittest.TestCase):
    def test_en_prise_undefended_queen(self) -> None:
        # Black pawn c6 attacks the undefended white queen on d5.
        board = chess.Board("4k3/8/2p5/3Q4/8/8/8/4K3 w - - 0 1")
        self.assertTrue(classify.is_en_prise(board, chess.D5))

    def test_not_en_prise_when_defended_by_equal(self) -> None:
        # Black pawn d5 attacked by c4 pawn but defended by e6 pawn (equal trade).
        board = chess.Board("4k3/8/4p3/3p4/2P5/8/8/4K3 w - - 0 1")
        self.assertFalse(classify.is_en_prise(board, chess.D5))

    def test_is_fork_knight_hits_king_and_queen(self) -> None:
        board = chess.Board("3q3k/8/8/6N1/8/8/8/4K3 w - - 0 1")
        self.assertTrue(classify.is_fork(board, uci("g5f7")))

    def test_is_discovered_attack_opens_rook_line_to_queen(self) -> None:
        board = chess.Board("4r2k/8/4n3/8/4Q3/8/8/K7 b - - 0 1")
        self.assertTrue(classify.is_discovered_attack(board, uci("e6c5"), chess.WHITE))

    def test_capture_wins_free_piece(self) -> None:
        board = chess.Board("4k3/8/8/8/3n4/8/8/3RK3 w - - 0 1")
        self.assertTrue(classify.capture_wins_material(board, uci("d1d4")))

    def test_capture_loses_material(self) -> None:
        # Queen grabs a pawn defended by another pawn.
        board = chess.Board("4k3/8/2p5/3p4/8/3Q4/8/4K3 w - - 0 1")
        self.assertTrue(classify.capture_loses_material(board, uci("d3d5")))

    def test_phase_detection(self) -> None:
        self.assertEqual(classify.game_phase(chess.Board(), 1), "opening")
        endgame = chess.Board("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")
        self.assertEqual(classify.game_phase(endgame, 40), "endgame")


class ClassifyFindingTests(unittest.TestCase):
    def test_hung_piece(self) -> None:
        before = chess.Board("4k3/8/2p5/8/8/8/8/3QK3 w - - 0 1")
        your_move = uci("d1d5")  # queen to a square the c6 pawn attacks
        after = before.copy()
        after.push(your_move)
        category, motifs, _ = classify.classify_finding(
            before_board=before,
            your_move=your_move,
            best_move=uci("d1d2"),
            before_pv=[uci("d1d2")],
            after_board=after,
            after_pv=[uci("c6d5")],
            eval_before_cp=30,
            eval_after_cp=-870,
            user_color=chess.WHITE,
            move_number=1,
        )
        self.assertEqual(category, "hung_piece")
        self.assertIn("hangingPiece", motifs)

    def test_allowed_fork(self) -> None:
        after = chess.Board("4k3/8/8/4n3/5Q2/8/8/4K3 b - - 0 1")
        category, motifs, _ = classify.classify_finding(
            before_board=chess.Board(),
            your_move=uci("e2e4"),
            best_move=None,
            before_pv=[],
            after_board=after,
            after_pv=[uci("e5d3")],  # ...Nd3 forks king+queen
            eval_before_cp=20,
            eval_after_cp=-500,
            user_color=chess.WHITE,
            move_number=20,
        )
        self.assertEqual(category, "allowed_fork")
        self.assertIn("fork", motifs)

    def test_allowed_discovered_attack(self) -> None:
        after = chess.Board("4r2k/8/4n3/8/4Q3/8/8/K7 b - - 0 1")
        category, motifs, _ = classify.classify_finding(
            before_board=chess.Board(),
            your_move=uci("e2e4"),
            best_move=None,
            before_pv=[],
            after_board=after,
            after_pv=[uci("e6c5")],  # knight moves, rook on e8 now attacks queen on e4
            eval_before_cp=20,
            eval_after_cp=-500,
            user_color=chess.WHITE,
            move_number=20,
        )
        self.assertEqual(category, "allowed_discovered")
        self.assertIn("discoveredAttack", motifs)

    def test_missed_free_capture(self) -> None:
        before = chess.Board("4k3/8/8/8/3n4/8/8/3RK3 w - - 0 1")
        after = before.copy()
        after.push(uci("e1e2"))  # quiet move instead of taking the free knight
        category, _, _ = classify.classify_finding(
            before_board=before,
            your_move=uci("e1e2"),
            best_move=uci("d1d4"),  # Rxd4 wins the knight
            before_pv=[uci("d1d4")],
            after_board=after,
            after_pv=[],
            eval_before_cp=300,
            eval_after_cp=0,
            user_color=chess.WHITE,
            move_number=20,
        )
        self.assertEqual(category, "missed_free_capture")

    def test_walked_into_mate(self) -> None:
        category, motifs, _ = classify.classify_finding(
            before_board=chess.Board(),
            your_move=uci("e2e4"),
            best_move=None,
            before_pv=[],
            after_board=chess.Board(),
            after_pv=[],
            eval_before_cp=-50,
            eval_after_cp=-100000,
            user_color=chess.WHITE,
            move_number=25,
        )
        self.assertEqual(category, "walked_into_mate")
        self.assertIn("mate", motifs)


if __name__ == "__main__":
    unittest.main()
