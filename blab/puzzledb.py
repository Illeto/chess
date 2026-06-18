"""Build and query a local SQLite of Lichess puzzles, for topping up lessons.

`build`/`download_and_build` stream the public Lichess puzzle CSV, keep only
beginner-rated puzzles whose themes match our categories, and store them so a
lesson can pull a few extra theme-matched drills. Stored positions are already
advanced to the solver's move (Lichess puzzles start one ply before the solution),
so they slot into the same server-authoritative solver as the user's own puzzles.

zstandard is only needed for building; querying uses the stdlib sqlite3.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import chess

DB_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
USER_AGENT = "chess-blunder-lab/0.1 (local personal analysis tool)"
DEFAULT_MAX_RATING = 1300

# Cause category -> Lichess theme tags used to fetch matching outside puzzles.
CATEGORY_THEMES = {
    "hung_piece": ["hangingPiece"],
    "allowed_fork": ["fork"],
    "allowed_pin_skewer": ["pin", "skewer"],
    "allowed_discovered": ["discoveredAttack"],
    "walked_into_mate": ["backRankMate", "mateIn1", "mateIn2", "mate"],
    "trade_counting_error": ["capturingDefender"],
    "missed_free_capture": ["hangingPiece"],
    "missed_tactic": ["fork", "pin", "skewer", "discoveredAttack", "sacrifice"],
    "positional_other": [],
}

# All themes we bother storing (union of the above).
KEEP_THEMES = {t for themes in CATEGORY_THEMES.values() for t in themes}


def default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "puzzles.sqlite"


def available(db_path: Optional[Path] = None) -> bool:
    path = Path(db_path) if db_path else default_db_path()
    return path.exists() and path.stat().st_size > 0


# ---------- build ----------

def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def _init_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        DROP TABLE IF EXISTS puzzles;
        DROP TABLE IF EXISTS puzzle_themes;
        CREATE TABLE puzzles (
            puzzle_id TEXT PRIMARY KEY,
            fen TEXT NOT NULL,
            best_uci TEXT NOT NULL,
            pv_uci TEXT NOT NULL,
            side TEXT NOT NULL,
            rating INTEGER NOT NULL,
            themes TEXT NOT NULL,
            url TEXT
        );
        CREATE TABLE puzzle_themes (puzzle_id TEXT NOT NULL, theme TEXT NOT NULL);
        CREATE INDEX idx_puzzle_themes ON puzzle_themes(theme, puzzle_id);
        """
    )


def _solver_position(fen: str, moves: Sequence[str]):
    """Advance the Lichess setup move; return (solver_fen, side, best_uci, pv_uci)."""
    board = chess.Board(fen)
    board.push(chess.Move.from_uci(moves[0]))
    side = "white" if board.turn == chess.WHITE else "black"
    return board.fen(), side, moves[1], " ".join(moves[1:])


def build_from_rows(
    db_path: Path,
    rows: Iterable[Sequence[str]],
    max_rating: int = DEFAULT_MAX_RATING,
    keep_themes: Optional[set] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Build the DB from CSV rows (header already skipped). Returns puzzles kept."""
    keep = keep_themes if keep_themes is not None else KEEP_THEMES
    con = _connect(db_path)
    _init_schema(con)
    kept = scanned = 0
    puzzle_batch: List[tuple] = []
    theme_batch: List[tuple] = []

    def flush():
        con.executemany(
            "INSERT OR IGNORE INTO puzzles VALUES (?,?,?,?,?,?,?,?)", puzzle_batch
        )
        con.executemany("INSERT INTO puzzle_themes VALUES (?,?)", theme_batch)
        con.commit()
        puzzle_batch.clear()
        theme_batch.clear()

    for row in rows:
        scanned += 1
        if progress_cb and scanned % 200000 == 0:
            progress_cb(scanned, kept)
        if len(row) < 8:
            continue
        themes = set(row[7].split())
        matched = themes & keep
        if not matched:
            continue
        try:
            rating = int(row[3])
        except ValueError:
            continue
        if rating > max_rating:
            continue
        moves = row[2].split()
        if len(moves) < 2:
            continue
        try:
            fen, side, best_uci, pv_uci = _solver_position(row[1], moves)
        except (ValueError, IndexError):
            continue
        puzzle_id = row[0]
        puzzle_batch.append(
            (puzzle_id, fen, best_uci, pv_uci, side, rating, row[7], row[8] if len(row) > 8 else "")
        )
        for theme in matched:
            theme_batch.append((puzzle_id, theme))
        kept += 1
        if len(puzzle_batch) >= 5000:
            flush()

    flush()
    con.close()
    if progress_cb:
        progress_cb(scanned, kept)
    return kept


def download_and_build(
    db_path: Optional[Path] = None,
    max_rating: int = DEFAULT_MAX_RATING,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    url: str = DB_URL,
) -> int:
    import zstandard

    path = Path(db_path) if db_path else default_db_path()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        reader = zstandard.ZstdDecompressor().stream_reader(response)
        text = io.TextIOWrapper(reader, encoding="utf-8", newline="")
        csv_rows = csv.reader(text)
        next(csv_rows, None)  # header
        return build_from_rows(path, csv_rows, max_rating=max_rating, progress_cb=progress_cb)


# ---------- query ----------

def _row_to_dict(row: sqlite3.Row) -> Dict[str, object]:
    return {
        "puzzle_id": row["puzzle_id"],
        "fen": row["fen"],
        "best_uci": row["best_uci"],
        "pv_uci": row["pv_uci"],
        "side": row["side"],
        "rating": row["rating"],
        "themes": row["themes"],
        "url": row["url"],
    }


def query(
    themes: Sequence[str],
    limit: int,
    max_rating: int = DEFAULT_MAX_RATING,
    db_path: Optional[Path] = None,
) -> List[Dict[str, object]]:
    themes = [t for t in themes if t]
    if not themes or limit <= 0:
        return []
    path = Path(db_path) if db_path else default_db_path()
    if not available(path):
        return []
    placeholders = ",".join("?" for _ in themes)
    con = _connect(path)
    try:
        cur = con.execute(
            f"""
            SELECT DISTINCT p.* FROM puzzles p
            JOIN puzzle_themes t ON t.puzzle_id = p.puzzle_id
            WHERE t.theme IN ({placeholders}) AND p.rating <= ?
            ORDER BY RANDOM() LIMIT ?
            """,
            [*themes, max_rating, limit],
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def get(puzzle_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, object]]:
    path = Path(db_path) if db_path else default_db_path()
    if not available(path):
        return None
    con = _connect(path)
    try:
        row = con.execute(
            "SELECT * FROM puzzles WHERE puzzle_id = ?", [puzzle_id]
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        con.close()
