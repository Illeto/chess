"""Per-user spaced-repetition store so weak patterns resurface over time.

A local SQLite at ``~/.blunder_lab/progress.db`` records every drill attempt and an
SM-2-style schedule per puzzle (keyed by position + best move, so the same mistake
recurs across analysis runs). Categories you keep getting wrong stay "due" sooner;
ones you've nailed a few times drift further out. Pure stdlib — no engine, no network.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional, Set

MASTER_REPS = 2  # answered right this many times in a row → "mastered"
RELEARN_SECONDS = 600  # a wrong answer comes due again ~10 minutes out


def default_db_path() -> Path:
    return Path.home() / ".blunder_lab" / "progress.db"


def puzzle_key(fen: str, best_uci: str) -> str:
    """Stable identity for a drill across runs."""
    return hashlib.sha256(f"{fen}|{best_uci}".encode("utf-8")).hexdigest()[:24]


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS srs (
            username TEXT NOT NULL,
            puzzle_key TEXT NOT NULL,
            category TEXT,
            ease REAL NOT NULL,
            reps INTEGER NOT NULL,
            interval_days REAL NOT NULL,
            due REAL NOT NULL,
            attempts INTEGER NOT NULL,
            correct INTEGER NOT NULL,
            last_ts REAL NOT NULL,
            PRIMARY KEY (username, puzzle_key)
        )
        """
    )
    return con


def _schedule(ease: float, reps: int, interval: float, correct: bool, now: float):
    """One SM-2 step. Quality is 5 for a correct answer, 2 for a wrong one."""
    quality = 5 if correct else 2
    if quality < 3:
        reps = 0
        interval = 0.0
    else:
        reps += 1
        if reps == 1:
            interval = 1.0
        elif reps == 2:
            interval = 6.0
        else:
            interval = round(interval * ease, 2)
        ease = max(1.3, ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    due = now + (interval * 86400 if interval > 0 else RELEARN_SECONDS)
    return ease, reps, interval, due


def record_attempt(
    username: str,
    fen: str,
    best_uci: str,
    category: str,
    correct: bool,
    db_path: Optional[Path] = None,
    now: Optional[float] = None,
) -> dict:
    """Record one drill attempt and advance its schedule. Returns the new state."""
    now = time.time() if now is None else now
    db = Path(db_path) if db_path else default_db_path()
    key = puzzle_key(fen, best_uci)
    con = _connect(db)
    try:
        row = con.execute(
            "SELECT * FROM srs WHERE username = ? AND puzzle_key = ?", (username, key)
        ).fetchone()
        ease = row["ease"] if row else 2.5
        reps = row["reps"] if row else 0
        interval = row["interval_days"] if row else 0.0
        attempts = (row["attempts"] if row else 0) + 1
        correct_count = (row["correct"] if row else 0) + (1 if correct else 0)

        ease, reps, interval, due = _schedule(ease, reps, interval, bool(correct), now)
        con.execute(
            """
            INSERT INTO srs (username, puzzle_key, category, ease, reps, interval_days,
                             due, attempts, correct, last_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, puzzle_key) DO UPDATE SET
                category = excluded.category, ease = excluded.ease, reps = excluded.reps,
                interval_days = excluded.interval_days, due = excluded.due,
                attempts = excluded.attempts, correct = excluded.correct,
                last_ts = excluded.last_ts
            """,
            (username, key, category, ease, reps, interval, due, attempts, correct_count, now),
        )
        con.commit()
        return {"reps": reps, "interval_days": interval, "due": due, "mastered": reps >= MASTER_REPS}
    finally:
        con.close()


def category_progress(
    username: str, db_path: Optional[Path] = None, now: Optional[float] = None
) -> Dict[str, dict]:
    """Per-category counts: positions seen, mastered, due for review, and accuracy."""
    now = time.time() if now is None else now
    db = Path(db_path) if db_path else default_db_path()
    if not db.exists():
        return {}
    con = _connect(db)
    try:
        out: Dict[str, dict] = {}
        rows = con.execute(
            """
            SELECT category,
                   COUNT(*) AS seen,
                   SUM(CASE WHEN reps >= ? THEN 1 ELSE 0 END) AS mastered,
                   SUM(CASE WHEN due <= ? THEN 1 ELSE 0 END) AS due,
                   SUM(attempts) AS attempts,
                   SUM(correct) AS correct
            FROM srs WHERE username = ? GROUP BY category
            """,
            (MASTER_REPS, now, username),
        )
        for r in rows:
            out[r["category"] or "positional_other"] = {
                "seen": r["seen"],
                "mastered": r["mastered"] or 0,
                "due": r["due"] or 0,
                "attempts": r["attempts"] or 0,
                "correct": r["correct"] or 0,
            }
        return out
    finally:
        con.close()


def due_keys(
    username: str, db_path: Optional[Path] = None, now: Optional[float] = None
) -> Set[str]:
    """Puzzle keys currently due for review (also matches never-mastered relearns)."""
    now = time.time() if now is None else now
    db = Path(db_path) if db_path else default_db_path()
    if not db.exists():
        return set()
    con = _connect(db)
    try:
        return {
            r[0]
            for r in con.execute(
                "SELECT puzzle_key FROM srs WHERE username = ? AND due <= ?", (username, now)
            )
        }
    finally:
        con.close()
