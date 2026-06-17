"""A single shared Stockfish process for interactive move grading.

Opening Stockfish per request is wasteful, so the solver shares one engine guarded
by a lock. If the engine crashes (``EngineTerminatedError``) it is discarded and
recreated on the next call. The background analysis job uses its own engine
(``run_analysis`` opens one), so a long analyze never blocks grading here.
"""

from __future__ import annotations

import atexit
import threading
from typing import Optional, Tuple

import chess
import chess.engine

import blunder_lab as lab

_lock = threading.Lock()
_engine: Optional[chess.engine.SimpleEngine] = None


def ready() -> bool:
    """True if a Stockfish binary can be resolved."""
    try:
        lab.resolve_engine(None)
        return True
    except lab.UserFacingError:
        return False


def engine_path() -> Optional[str]:
    try:
        return str(lab.resolve_engine(None))
    except lab.UserFacingError:
        return None


def _ensure() -> chess.engine.SimpleEngine:
    global _engine
    if _engine is None:
        path = lab.resolve_engine(None)
        _engine = chess.engine.SimpleEngine.popen_uci(str(path))
    return _engine


def _discard_unlocked() -> None:
    global _engine
    if _engine is not None:
        try:
            _engine.quit()
        except Exception:
            pass
        _engine = None


def close() -> None:
    """Close the shared engine process if it has been opened."""
    with _lock:
        _discard_unlocked()


def grade(
    board: chess.Board,
    move: chess.Move,
    best_uci: str,
    accept_cp: int,
    depth: int,
) -> Tuple[bool, str]:
    """Grade ``move`` via the shared engine, reusing ``lab.grade_move``.

    Falls back to exact-match grading (no engine) when Stockfish is unavailable.
    """
    limit = chess.engine.Limit(depth=depth)
    if not ready():
        return lab.grade_move(board, move, best_uci, None, limit, accept_cp)

    with _lock:
        try:
            return lab.grade_move(board, move, best_uci, _ensure(), limit, accept_cp)
        except chess.engine.EngineError:
            _discard_unlocked()
            return lab.grade_move(board, move, best_uci, _ensure(), limit, accept_cp)


atexit.register(close)
