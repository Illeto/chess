"""Flask app for the local Chess Blunder Lab GUI.

Server-authoritative: the client never sends puzzle answers or arbitrary FENs.
Legal moves and grading are scoped to a stored puzzle index, loaded from disk.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import chess
import chess.svg
from flask import Flask, Response, abort, jsonify, render_template, request

import blunder_lab as lab
from blab import aiwriter
from blab import classify
from blab import lessons as lessons_mod
from blab import profile as error_profile
from blab import puzzledb

from . import engine_pool, jobs

GRADE_DEPTH = 12
GRADE_ACCEPT_CP = 30
BOARD_SIZE = 420
TIME_CLASSES = {"bullet", "blitz", "rapid", "daily"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
RUN_ID_STAMP_RE = re.compile(r"^(.+)_([0-9]{8}_[0-9]{6})$")


def create_app() -> Flask:
    app = Flask(__name__)

    # ---------- run discovery / validation ----------

    def run_dirs() -> Dict[str, Path]:
        """run_id -> directory, across known analysis roots (cwd preferred)."""
        found: Dict[str, Path] = {}
        for root in lab.analysis_roots(Path("analysis")):
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                if (child / "blunders.csv").exists() or (child / "report.md").exists():
                    found.setdefault(child.name, child)
        return found

    def resolve_run_dir(run_id: str) -> Path:
        if "/" in run_id or "\\" in run_id or run_id in ("", ".", ".."):
            abort(404)
        path = run_dirs().get(run_id)
        if path is None:
            abort(404)
        return path

    def read_rows(path: Path) -> List[dict]:
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def run_summary(run_id: str, path: Path) -> dict:
        findings = read_rows(path / "blunders.csv")
        counts = {"inaccuracy": 0, "mistake": 0, "blunder": 0}
        for row in findings:
            kind = row.get("kind", "")
            if kind in counts:
                counts[kind] += 1
        puzzles = read_rows(path / "puzzles.csv")
        match = RUN_ID_STAMP_RE.match(run_id)
        if match:
            username, stamp = match.groups()
        else:
            username, _, stamp = run_id.partition("_")
        return {
            "id": run_id,
            "username": username or run_id,
            "stamp": stamp,
            "findings": len(findings),
            "puzzles": len(puzzles),
            **counts,
        }

    # ---------- HTML pages ----------

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/run/<run_id>/review")
    def review_page(run_id: str):
        resolve_run_dir(run_id)
        return render_template("review.html", run_id=run_id)

    @app.get("/run/<run_id>/solve")
    def solve_page(run_id: str):
        resolve_run_dir(run_id)
        return render_template("solve.html", run_id=run_id)

    @app.get("/run/<run_id>/profile")
    def profile_page(run_id: str):
        resolve_run_dir(run_id)
        return render_template("profile.html", run_id=run_id)

    # ---------- general API ----------

    @app.get("/api/engine")
    def api_engine():
        return jsonify(ready=engine_pool.ready(), path=engine_pool.engine_path())

    @app.get("/api/piece/<sym>")
    def api_piece(sym: str):
        if len(sym) != 1 or sym not in "PNBRQKpnbrqk":
            abort(404)
        svg = chess.svg.piece(chess.Piece.from_symbol(sym))
        return Response(
            svg,
            mimetype="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/runs")
    def api_runs():
        items = [run_summary(rid, path) for rid, path in run_dirs().items()]
        items.sort(key=lambda r: r["stamp"], reverse=True)
        return jsonify(runs=items)

    @app.post("/api/analyze")
    def api_analyze():
        data = request.get_json(silent=True) or {}
        params, error = _analysis_params(data)
        if error:
            return jsonify(error=error), 400
        job_id = jobs.start(params)
        return jsonify(job_id=job_id), 202

    @app.get("/api/jobs/<job_id>")
    def api_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            abort(404)
        return jsonify(job)

    # ---------- review API ----------

    @app.get("/api/runs/<run_id>/profile")
    def api_profile(run_id: str):
        path = resolve_run_dir(run_id)
        rows = read_rows(path / "blunders.csv")
        return jsonify(profile=error_profile.build_error_profile(rows))

    @app.get("/api/runs/<run_id>/lessons/<category>")
    def api_lesson(run_id: str, category: str):
        if category not in classify.CATEGORIES:
            abort(404)
        path = resolve_run_dir(run_id)
        rows = lab.load_puzzle_rows(path / "puzzles.csv")
        return jsonify(lessons_mod.build_lesson(category, rows))

    @app.get("/api/runs/<run_id>/findings")
    def api_findings(run_id: str):
        path = resolve_run_dir(run_id)
        rows = read_rows(path / "blunders.csv")
        items = [
            {
                "index": i,
                "kind": row.get("kind", ""),
                "move_number": row.get("move_number", ""),
                "user_color": row.get("user_color", ""),
                "your_move_san": row.get("your_move_san", ""),
                "loss_cp": row.get("loss_cp", ""),
                "theme": row.get("theme", ""),
                "url": row.get("url", ""),
            }
            for i, row in enumerate(rows)
        ]
        return jsonify(count=len(items), items=items)

    @app.get("/api/runs/<run_id>/findings/<int:n>")
    def api_finding(run_id: str, n: int):
        path = resolve_run_dir(run_id)
        rows = read_rows(path / "blunders.csv")
        if not 0 <= n < len(rows):
            abort(404)
        row = rows[n]
        svg = _finding_svg(row)
        note, note_source = aiwriter.coach(
            {
                "category": row.get("category", ""),
                "your_move_san": row.get("your_move_san", ""),
                "best_move_san": row.get("best_move_san", ""),
                "pv_san": row.get("pv_san", ""),
                "motifs": row.get("motifs", ""),
                "eval_before": row.get("eval_before", ""),
                "eval_after": row.get("eval_after", ""),
                "user_color": row.get("user_color", ""),
            }
        )
        return jsonify(
            index=n,
            count=len(rows),
            category=row.get("category", ""),
            note=note,
            note_source=note_source,
            kind=row.get("kind", ""),
            move_number=row.get("move_number", ""),
            user_color=row.get("user_color", ""),
            your_move_san=row.get("your_move_san", ""),
            best_move_san=row.get("best_move_san", ""),
            pv_san=row.get("pv_san", ""),
            eval_before=row.get("eval_before", ""),
            eval_after=row.get("eval_after", ""),
            loss_cp=row.get("loss_cp", ""),
            theme=row.get("theme", ""),
            url=row.get("url", ""),
            fen=row.get("fen", ""),
            svg=svg,
        )

    # ---------- solver API (server-authoritative) ----------

    @app.get("/api/runs/<run_id>/puzzles")
    def api_puzzles(run_id: str):
        path = resolve_run_dir(run_id)
        rows = lab.load_puzzle_rows(path / "puzzles.csv")
        items = [
            {
                "index": i,
                "theme": row.get("theme", ""),
                "user_color": row.get("user_color", ""),
                "move_number": row.get("move_number", ""),
            }
            for i, row in enumerate(rows)
        ]
        return jsonify(count=len(items), items=items)

    @app.get("/api/runs/<run_id>/puzzles/<int:i>/legal")
    def api_legal(run_id: str, i: int):
        board, _row = _load_puzzle(run_id, i)
        return jsonify(
            fen=board.fen(),
            side="white" if board.turn == chess.WHITE else "black",
            legal=sorted(m.uci() for m in board.legal_moves),
        )

    @app.get("/api/runs/<run_id>/puzzles/<int:i>/hint")
    def api_hint(run_id: str, i: int):
        board, row = _load_puzzle(run_id, i)
        best_uci = (row.get("best_move_uci") or "").strip()
        try:
            move = chess.Move.from_uci(best_uci)
        except ValueError:
            return jsonify(square=None, piece=None)
        piece = board.piece_at(move.from_square)
        name = chess.piece_name(piece.piece_type).title() if piece else None
        return jsonify(square=chess.square_name(move.from_square), piece=name)

    @app.get("/api/runs/<run_id>/puzzles/<int:i>/line")
    def api_line(run_id: str, i: int):
        # The best line as a sequence of (san, uci, fen-after) so the client can
        # replay it on the board. Reveals the answer, so the UI only fetches it
        # after the move has been graded.
        board, row = _load_puzzle(run_id, i)
        moves = (row.get("pv_uci") or row.get("best_move_uci") or "").split()
        steps = []
        replay = board.copy()
        for token in moves:
            try:
                move = chess.Move.from_uci(token)
            except ValueError:
                break
            if move not in replay.legal_moves:
                break
            san = replay.san(move)
            replay.push(move)
            steps.append({"san": san, "uci": token, "fen": replay.fen()})
        return jsonify(start_fen=board.fen(), steps=steps)

    @app.post("/api/runs/<run_id>/puzzles/<int:i>/grade")
    def api_grade(run_id: str, i: int):
        board, row = _load_puzzle(run_id, i)
        data = request.get_json(silent=True) or {}
        raw = (data.get("move") or "").strip()
        move = lab.parse_move(board, raw)
        if move is None:
            return jsonify(error="Illegal or unparseable move."), 400
        best_uci = (row.get("best_move_uci") or "").strip()
        correct, detail = engine_pool.grade(
            board, move, best_uci, GRADE_ACCEPT_CP, GRADE_DEPTH
        )
        return jsonify(
            correct=correct,
            detail=detail,
            your_san=lab.safe_san(board, move),
            best_san=(row.get("best_move_san") or "").strip(),
            pv_san=(row.get("pv_san") or row.get("best_move_san") or "").strip(),
        )

    # ---------- Lichess DB puzzles (lesson top-ups, server-authoritative) ----------

    @app.get("/api/db/puzzles/<pid>/legal")
    def api_db_legal(pid: str):
        board, row = _load_db_puzzle(pid)
        return jsonify(
            fen=board.fen(),
            side="white" if board.turn == chess.WHITE else "black",
            legal=sorted(m.uci() for m in board.legal_moves),
            theme=row["themes"],
            rating=row["rating"],
        )

    @app.get("/api/db/puzzles/<pid>/hint")
    def api_db_hint(pid: str):
        board, row = _load_db_puzzle(pid)
        try:
            move = chess.Move.from_uci(row["best_uci"])
        except ValueError:
            return jsonify(square=None, piece=None)
        piece = board.piece_at(move.from_square)
        name = chess.piece_name(piece.piece_type).title() if piece else None
        return jsonify(square=chess.square_name(move.from_square), piece=name)

    @app.get("/api/db/puzzles/<pid>/line")
    def api_db_line(pid: str):
        board, row = _load_db_puzzle(pid)
        return jsonify(start_fen=board.fen(), steps=_line_steps(board, row["pv_uci"]))

    @app.post("/api/db/puzzles/<pid>/grade")
    def api_db_grade(pid: str):
        board, row = _load_db_puzzle(pid)
        data = request.get_json(silent=True) or {}
        move = lab.parse_move(board, (data.get("move") or "").strip())
        if move is None:
            return jsonify(error="Illegal or unparseable move."), 400
        correct, detail = engine_pool.grade(
            board, move, row["best_uci"], GRADE_ACCEPT_CP, GRADE_DEPTH
        )
        try:
            best_san = board.san(chess.Move.from_uci(row["best_uci"]))
        except ValueError:
            best_san = row["best_uci"]
        return jsonify(
            correct=correct,
            detail=detail,
            your_san=lab.safe_san(board, move),
            best_san=best_san,
            pv_san=_pv_san(board, row["pv_uci"]) or best_san,
        )

    # ---------- internals ----------

    def _load_puzzle(run_id: str, i: int) -> Tuple[chess.Board, dict]:
        path = resolve_run_dir(run_id)
        rows = lab.load_puzzle_rows(path / "puzzles.csv")
        if not 0 <= i < len(rows):
            abort(404)
        row = rows[i]
        try:
            board = chess.Board(row.get("fen", ""))
        except ValueError:
            abort(404)
        return board, row

    def _load_db_puzzle(pid: str) -> Tuple[chess.Board, dict]:
        row = puzzledb.get(pid)
        if not row:
            abort(404)
        try:
            board = chess.Board(row["fen"])
        except ValueError:
            abort(404)
        return board, row

    def _line_steps(board: chess.Board, pv_uci: str) -> list:
        steps = []
        replay = board.copy()
        for token in (pv_uci or "").split():
            try:
                move = chess.Move.from_uci(token)
            except ValueError:
                break
            if move not in replay.legal_moves:
                break
            san = replay.san(move)
            replay.push(move)
            steps.append({"san": san, "uci": token, "fen": replay.fen()})
        return steps

    def _pv_san(board: chess.Board, pv_uci: str) -> str:
        return " ".join(s["san"] for s in _line_steps(board, pv_uci))

    return app


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _analysis_params(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    username = (data.get("username") or "").strip()
    if not username:
        return None, "A Chess.com username is required."
    if not USERNAME_RE.match(username):
        return None, "Use a Chess.com username with only letters, numbers, underscores, or hyphens."

    time_class = (data.get("time_class") or "").strip() or None
    if time_class is not None and time_class not in TIME_CLASSES:
        return None, "Time class must be one of bullet, blitz, rapid, or daily."

    months, error = _bounded_int(data, "months", 1, 24)
    if error:
        return None, error
    max_games, error = _bounded_int(data, "max_games", 1, 500)
    if error:
        return None, error
    depth, error = _bounded_int(data, "depth", 4, 20)
    if error:
        return None, error

    return {
        "username": username,
        "months": months,
        "max_games": max_games,
        "time_class": time_class,
        "depth": depth,
    }, None


def _bounded_int(
    data: dict, field: str, minimum: int, maximum: int
) -> Tuple[Optional[int], Optional[str]]:
    raw = data.get(field)
    if raw is None or raw == "":
        return None, None
    value = _as_int(raw)
    if value is None:
        return None, f"{field.replace('_', ' ').title()} must be a number."
    if not minimum <= value <= maximum:
        return None, f"{field.replace('_', ' ').title()} must be between {minimum} and {maximum}."
    return value, None


def _finding_svg(row: dict) -> str:
    try:
        board = chess.Board(row.get("fen", ""))
    except ValueError:
        return ""
    orientation = chess.WHITE if row.get("user_color") == "White" else chess.BLACK
    arrows = []
    arrows += _arrow(row.get("best_move_uci"), "green")
    arrows += _arrow(row.get("your_move_uci"), "red")
    return chess.svg.board(
        board, orientation=orientation, arrows=arrows, size=BOARD_SIZE, coordinates=True
    )


def _arrow(uci: Optional[str], color: str) -> list:
    if not uci:
        return []
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return []
    return [chess.svg.Arrow(move.from_square, move.to_square, color=color)]
