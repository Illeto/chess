"""In-memory background analysis jobs for the GUI.

A single daemon worker thread processes one analysis at a time (avoids competing
Stockfish processes). Jobs are not persisted across server restarts; the run
artifacts they produce live in ``analysis/`` like any CLI run.
"""

from __future__ import annotations

import queue
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional

import blunder_lab as lab

_jobs: Dict[str, dict] = {}
_lock = threading.Lock()
_queue: "queue.Queue[str]" = queue.Queue()
_worker_started = False

# Analysis defaults mirror the CLI argparse defaults.
_DEFAULTS = dict(
    months=3,
    max_games=25,
    time_class=None,
    depth=10,
    skip_opening_plies=8,
    inaccuracy_cp=75,
    mistake_cp=150,
    blunder_cp=300,
    puzzle_min_loss_cp=150,
    puzzle_min_eval_cp=-50,
    max_pv_moves=6,
)


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True).start()
            _worker_started = True


def start(params: dict) -> str:
    """Queue an analysis job, returning its id."""
    _ensure_worker()
    job_id = uuid.uuid4().hex[:12]
    merged = {**_DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    with _lock:
        _jobs[job_id] = {
            "status": "queued",
            "phase": "queued",
            "done": 0,
            "total": 0,
            "label": "",
            "run_id": None,
            "error": None,
            "params": merged,
        }
    _queue.put(job_id)
    return job_id


def get(job_id: str) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {k: v for k, v in job.items() if k != "params"}


def _update(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _worker() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run(job_id)
        finally:
            _queue.task_done()


def _run(job_id: str) -> None:
    with _lock:
        params = dict(_jobs[job_id]["params"])
    try:
        _update(job_id, status="running", phase="fetching", label="fetching games")
        username = params["username"]
        engine_path = lab.resolve_engine(None)
        output_dir = lab.default_output_dir(username).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        settings = lab.AnalysisSettings(
            username=username,
            engine_path=engine_path,
            depth=params["depth"],
            movetime_ms=None,
            threads=None,
            hash_mb=None,
            skip_opening_plies=params["skip_opening_plies"],
            inaccuracy_cp=params["inaccuracy_cp"],
            mistake_cp=params["mistake_cp"],
            blunder_cp=params["blunder_cp"],
            puzzle_min_loss_cp=params["puzzle_min_loss_cp"],
            puzzle_min_eval_cp=params["puzzle_min_eval_cp"],
            max_pv_moves=params["max_pv_moves"],
        )

        sources = lab.fetch_chesscom_sources(
            username=username,
            months=params["months"],
            since=None,
            until=None,
            max_games=params["max_games"],
            time_class=params["time_class"],
            newest_first=True,
        )
        lab.write_raw_games_pgn(sources, output_dir / "raw_games.pgn")
        if not sources:
            raise lab.UserFacingError("No games matched the requested filters.")
        _update(job_id, total=len(sources))

        def cb(phase: str, done: int, total: int, label: str) -> None:
            _update(job_id, phase=phase, done=done, total=total, label=label)

        lab.run_analysis(settings, sources, output_dir, progress_cb=cb)
        _update(
            job_id,
            status="succeeded",
            phase="done",
            run_id=output_dir.name,
            label="done",
        )
    except lab.UserFacingError as exc:
        _update(job_id, status="failed", phase="error", error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        _update(job_id, status="failed", phase="error", error=f"{type(exc).__name__}: {exc}")
