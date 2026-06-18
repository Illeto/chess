"""Classify a flagged move into a named blunder category, motif tags, and phase.

The engine has already decided *that* a move lost eval and *what* the best line was;
this module decides *why it went wrong* in human terms, using only the board, the
played/best moves, and the engine's two lines (your best line and the opponent's
reply). Heuristics are simplified ports of the Lichess puzzle tagger (cook.py):
attackers/defenders, piece values, forks, and en-prise checks. Detection is
best-effort and tuned for beginner games; ``positional_other`` is the catch-all.

Primary output is one **cause category** (what the user should fix), plus a list of
**motif** tags (Lichess names) and a game **phase**.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import chess

# Cause categories, most-specific first (classification returns the first that fits).
CATEGORIES = [
    "walked_into_mate",
    "allowed_fork",
    "allowed_pin_skewer",
    "allowed_discovered",
    "hung_piece",
    "trade_counting_error",
    "missed_free_capture",
    "missed_tactic",
    "positional_other",
]

CATEGORY_LABELS = {
    "walked_into_mate": "Walked into mate",
    "allowed_fork": "Allowed a fork",
    "allowed_pin_skewer": "Allowed a pin/skewer",
    "allowed_discovered": "Allowed a discovered attack",
    "hung_piece": "Hung a piece",
    "trade_counting_error": "Lost a trade (counting)",
    "missed_free_capture": "Missed a free capture",
    "missed_tactic": "Missed a tactic",
    "positional_other": "Positional / other",
}

PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

MATE_THRESHOLD = 90000  # eval magnitudes at/above this are forced mates


def classify_finding(
    *,
    before_board: chess.Board,
    your_move: chess.Move,
    best_move: Optional[chess.Move],
    before_pv: Sequence[chess.Move],
    after_board: chess.Board,
    after_pv: Sequence[chess.Move],
    eval_before_cp: int,
    eval_after_cp: int,
    user_color: chess.Color,
    move_number: int,
) -> Tuple[str, List[str], str]:
    """Return (category, motifs, phase) for one flagged move."""
    motifs: List[str] = []
    phase = game_phase(after_board, move_number)
    opp_reply = after_pv[0] if after_pv else None

    # 1. You are getting mated now (and were not before).
    if eval_after_cp <= -MATE_THRESHOLD and eval_before_cp > -MATE_THRESHOLD:
        motifs.append("mate")
        if opp_reply is not None and _is_back_rank_mate(after_board, opp_reply, user_color):
            motifs.append("backRankMate")
        return "walked_into_mate", _dedup(motifs), phase

    # 2. Your move let the opponent win material — find the mechanism.
    hung = en_prise_squares(after_board, user_color)
    if opp_reply is not None and is_fork(after_board, opp_reply):
        motifs.append("fork")
        return "allowed_fork", _dedup(motifs), phase
    if opp_reply is not None and is_discovered_attack(after_board, opp_reply, user_color):
        motifs.append("discoveredAttack")
        return "allowed_discovered", _dedup(motifs), phase
    if hung:
        if opp_reply is not None and is_pin_or_skewer(after_board, opp_reply, user_color):
            motifs.append("pin")
            return "allowed_pin_skewer", _dedup(motifs), phase
        motifs.append("hangingPiece")
        return "hung_piece", _dedup(motifs), phase

    # 3. Your move was a capture that loses material in the exchange.
    if before_board.is_capture(your_move) and capture_loses_material(before_board, your_move):
        motifs.append("counting")
        return "trade_counting_error", _dedup(motifs), phase

    # 4. You missed something the engine would have played.
    if best_move is not None:
        if before_board.is_capture(best_move) and capture_wins_material(before_board, best_move):
            motifs.append("hangingPiece")
            return "missed_free_capture", _dedup(motifs), phase
        best_motifs = move_tactics(before_board, best_move)
        if best_motifs:
            return "missed_tactic", _dedup(motifs + best_motifs), phase

    return "positional_other", _dedup(motifs), phase


# ---------- board helpers ----------

def is_en_prise(board: chess.Board, square: chess.Square) -> bool:
    """A non-king piece that the opponent can win (undefended, or attacked by something cheaper)."""
    piece = board.piece_at(square)
    if piece is None or piece.piece_type == chess.KING:
        return False
    attackers = board.attackers(not piece.color, square)
    if not attackers:
        return False
    defenders = board.attackers(piece.color, square)
    if not defenders:
        return True
    cheapest = min(PIECE_VALUE[board.piece_at(s).piece_type] for s in attackers)
    return cheapest < PIECE_VALUE[piece.piece_type]


def en_prise_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
    return [
        sq
        for sq, pc in board.piece_map().items()
        if pc.color == color and is_en_prise(board, sq)
    ]


def is_fork(board: chess.Board, move: chess.Move) -> bool:
    """After ``move``, does the moved piece attack two or more valuable enemy targets?"""
    if move not in board.legal_moves:
        return False
    mover = board.turn
    nb = board.copy(stack=False)
    nb.push(move)
    sq = move.to_square
    piece = nb.piece_at(sq)
    if piece is None or piece.piece_type == chess.KING:
        return False
    attacker_value = PIECE_VALUE[piece.piece_type]
    targets = 0
    for target in nb.attacks(sq):
        tp = nb.piece_at(target)
        if tp is None or tp.color == mover:
            continue
        if tp.piece_type == chess.KING:
            targets += 1
        elif PIECE_VALUE[tp.piece_type] > attacker_value or not nb.attackers(tp.color, target):
            targets += 1
    return targets >= 2


def is_pin_or_skewer(board: chess.Board, move: chess.Move, victim_color: chess.Color) -> bool:
    """Approximate: after ``move``, a meaningful victim piece is absolutely pinned and attacked."""
    if move not in board.legal_moves:
        return False
    nb = board.copy(stack=False)
    nb.push(move)
    for sq, pc in nb.piece_map().items():
        if pc.color != victim_color or pc.piece_type == chess.KING:
            continue
        if PIECE_VALUE[pc.piece_type] < 300:
            continue
        if nb.is_pinned(victim_color, sq) and nb.attackers(not victim_color, sq):
            return True
    return False


def is_discovered_attack(board: chess.Board, move: chess.Move, victim_color: chess.Color) -> bool:
    """After ``move``, did a slider behind the moved piece newly attack a valuable victim?"""
    if move not in board.legal_moves:
        return False
    attacker_color = board.turn
    nb = board.copy(stack=False)
    nb.push(move)
    sliders = {chess.BISHOP, chess.ROOK, chess.QUEEN}

    for victim_sq, victim in nb.piece_map().items():
        if victim.color != victim_color:
            continue
        if victim.piece_type != chess.KING and PIECE_VALUE[victim.piece_type] < PIECE_VALUE[chess.ROOK]:
            continue
        before_attackers = set(board.attackers(attacker_color, victim_sq))
        after_attackers = set(nb.attackers(attacker_color, victim_sq))
        for attacker_sq in after_attackers - before_attackers:
            if attacker_sq == move.to_square:
                continue
            attacker = nb.piece_at(attacker_sq)
            if attacker and attacker.color == attacker_color and attacker.piece_type in sliders:
                return True
    return False


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return PIECE_VALUE[chess.PAWN]
    victim = board.piece_at(move.to_square)
    return PIECE_VALUE[victim.piece_type] if victim else 0


def capture_wins_material(board: chess.Board, move: chess.Move) -> bool:
    """Crude 1-ply SEE: capturing here nets material (free piece, or a winning trade)."""
    if not board.is_capture(move):
        return False
    victim = _captured_value(board, move)
    ours = PIECE_VALUE[board.piece_at(move.from_square).piece_type]
    nb = board.copy(stack=False)
    nb.push(move)
    recapturers = nb.attackers(nb.turn, move.to_square)
    if not recapturers:
        return victim > 0
    return victim - ours > 0


def capture_loses_material(board: chess.Board, move: chess.Move) -> bool:
    """Crude 1-ply SEE: this capture loses material (we grab less than we give back)."""
    if not board.is_capture(move):
        return False
    victim = _captured_value(board, move)
    ours = PIECE_VALUE[board.piece_at(move.from_square).piece_type]
    nb = board.copy(stack=False)
    nb.push(move)
    recapturers = nb.attackers(nb.turn, move.to_square)
    if not recapturers:
        return False
    return ours - victim > 0


def move_tactics(board: chess.Board, move: chess.Move) -> List[str]:
    """Tactic motifs of a move (used to describe a missed best move)."""
    motifs: List[str] = []
    if is_fork(board, move):
        motifs.append("fork")
    if move in board.legal_moves:
        nb = board.copy(stack=False)
        nb.push(move)
        if nb.is_checkmate():
            motifs.append("mate")
    return motifs


def _is_back_rank_mate(board: chess.Board, move: chess.Move, mated_color: chess.Color) -> bool:
    if move not in board.legal_moves:
        return False
    nb = board.copy(stack=False)
    nb.push(move)
    if not nb.is_checkmate():
        return False
    king_sq = nb.king(mated_color)
    if king_sq is None:
        return False
    back_rank = 0 if mated_color == chess.WHITE else 7
    return chess.square_rank(king_sq) == back_rank


def game_phase(board: chess.Board, move_number: int) -> str:
    non_pawn = sum(
        PIECE_VALUE[p.piece_type]
        for p in board.piece_map().values()
        if p.piece_type not in (chess.PAWN, chess.KING)
    )
    if non_pawn <= 1300:
        return "endgame"
    if move_number <= 10:
        return "opening"
    return "middlegame"


def _dedup(items: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(i for i in items if i))
