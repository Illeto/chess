import unittest

from blab.profile import build_error_profile, format_profile_lines


class ProfileTests(unittest.TestCase):
    def rows(self):
        return [
            {"category": "hung_piece", "motifs": "hangingPiece", "phase": "middlegame", "loss_cp": 300},
            {"category": "hung_piece", "motifs": "hangingPiece", "phase": "endgame", "loss_cp": 500},
            {"category": "missed_tactic", "motifs": "fork", "phase": "opening", "loss_cp": 200},
        ]

    def test_ranks_by_total_loss(self):
        prof = build_error_profile(self.rows())
        self.assertEqual(prof[0]["category"], "hung_piece")
        self.assertEqual(prof[0]["count"], 2)
        self.assertEqual(prof[0]["total_loss_cp"], 800)
        self.assertEqual(prof[0]["label"], "Hung a piece")
        self.assertEqual(prof[0]["motifs"][0], ("hangingPiece", 2))
        self.assertAlmostEqual(sum(g["share"] for g in prof), 1.0, places=5)

    def test_blank_category_falls_back(self):
        prof = build_error_profile([{"category": "", "motifs": "", "phase": "", "loss_cp": 100}])
        self.assertEqual(prof[0]["category"], "positional_other")

    def test_format_and_empty(self):
        text = "\n".join(format_profile_lines(build_error_profile(self.rows())))
        self.assertIn("Error Profile", text)
        self.assertIn("Hung a piece", text)
        self.assertEqual(build_error_profile([]), [])
        self.assertEqual(format_profile_lines([]), [])


if __name__ == "__main__":
    unittest.main()
