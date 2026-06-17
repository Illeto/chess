# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`blunder_lab.py` is a single-file CLI that fetches a Chess.com player's games (or
reads a local PGN), analyzes the user's moves with a UCI engine (Stockfish),
and exports a blunder report plus a study-puzzle set. It is a personal training
tool for a beginner-level player; defaults are tuned accordingly.

## Commands

```bash
python3 -m pip install -r requirements.txt   # only dep: python-chess

python3 blunder_lab.py install-engine        # download official Stockfish into engines/stockfish/
python3 blunder_lab.py analyze --username <chesscom_user>
python3 blunder_lab.py solve                 # interactive trainer over the newest puzzles.csv

python3 -m pip install -r requirements-web.txt   # optional: web GUI deps (Flask only)
python3 blunder_lab.py gui                    # local browser GUI at 127.0.0.1:5000
```

`--username` is a required argument; no personal handle is baked into the
`analyze` parser.

There is a small standard-library `unittest` suite for pure helpers. To verify
a change end-to-end without hitting the network, run those tests, then run
`analyze` against a local PGN and `solve` the result:

```bash
python3 -m unittest discover -v
python3 blunder_lab.py analyze --pgn some_games.pgn --depth 8
printf 'quit\n' | python3 blunder_lab.py solve --no-engine   # smoke-test the solver loop
```

`solve` reads from stdin, so drive it non-interactively by piping moves/commands
(`Nf3`, `g1f3`, `hint`, `skip`, `quit`) for testing.

## Architecture

The CLI lives in `blunder_lab.py` (~1500 lines), one module, four subcommands
(`install-engine`, `analyze`, `solve`, `gui`) dispatched from `main()` to
`build_parser()`; the GUI implementation lives in the `web/` package. Logic is plain functions over three
dataclasses: `AnalysisSettings` (run config), `GameSource` (a parsed game + its
raw Chess.com JSON), and `MoveFinding` (one flagged move; also serves as a puzzle
record). Errors meant for the user are raised as `UserFacingError` and printed
without a traceback.

**Engine resolution** (`resolve_engine`) is the same for
`analyze` and `solve`, in priority order: explicit `--engine` to `$STOCKFISH_EXECUTABLE`
to `stockfish` on `PATH` to `engines/stockfish/`. `install-engine` downloads the
correct asset for the OS/CPU (`stockfish_asset_name`), extracts it safely
(`safe_extract_tar` and `safe_extract_zip` guard path traversal), de-quarantines
it on macOS, symlinks it to `engines/stockfish/stockfish`, and sanity-checks
UCI before trusting it.

**Analysis pipeline** (`analyze_command` to `analyze_game`):
for each of the user's moves past the opening (`--skip-opening-plies`), it runs
the engine on the position **before** the move (its best line) and **after** the
played move, both scored from the mover's point of view (`score_for_color`).
`loss_cp = eval_before - eval_after`; `classify_loss` buckets it into
inaccuracy/mistake/blunder by centipawn thresholds. This is the standard
"centipawn loss vs. best play" method; keep the point-of-view consistent if you
touch it, or evals will silently invert. Mate is encoded as plus/minus `MATE_SCORE`
(100000) and game-over positions are scored by `terminal_score` instead of the
engine. The engine loop + output writing are factored into
`run_analysis(settings, sources, output_dir, progress_cb)` (phases analyzing →
writing → done), shared by `analyze_command` and the GUI's background job; fetching
games stays with each caller.

**Puzzle selection**: a finding becomes a puzzle only when
`loss_cp >= --puzzle-min-loss-cp` AND `eval_before >= --puzzle-min-eval-cp`
(default -50). The eval floor excludes positions that were already lost before
the mistake, so the puzzle set is "clean tactics you missed" rather than
damage-control. All blunders still appear in `report.md`/`blunders.csv`; the
floor only gates puzzles.

**Report focus** (`study_focus_lines`): the report summarizes repeated themes
and ranks games by blunders/mistakes/findings, so the user gets a study queue
instead of only a long list of positions.

**Solver** (`solve_command`): loads a `puzzles.csv` (newest
under `analysis/` by default), renders each board from the solver's side
(`render_board` flips for Black), and grades the typed move. With an engine it
accepts any move within `--accept-cp` of best (so good alternatives count);
with `--no-engine` it falls back to exact-match against the saved best move.

**Web GUI** (`web/` package; `gui` subcommand lazy-imports Flask). `web/app.py`
imports `blunder_lab` and is **server-authoritative**: legal moves and grading are
scoped to a stored puzzle index (`/api/runs/<id>/puzzles/<i>/legal` and `/grade`)
and load the FEN/best move from disk, so the browser never gets the answer before
submitting. `web/jobs.py` runs analysis on a single background worker thread via
`run_analysis`; `web/engine_pool.py` shares one lock-guarded Stockfish process for
grading and recreates it on `EngineTerminatedError`. Review boards are
server-rendered `chess.svg`; the solver uses a homemade HTML/CSS click board (no
third-party assets). Run-id inputs are validated against `analysis_roots()` to
reject path traversal. Web deps are isolated in `requirements-web.txt`. Tests live
in `tests/test_web.py` (Flask `test_client`; the engine-backed grade test is
guarded by engine availability).

## Outputs and conventions

`analyze` writes a timestamped dir `analysis/<username>_<timestamp>/` containing
`report.md`, `blunders.csv`, `puzzles.csv`, `puzzles.pgn`, and `raw_games.pgn`.

`engines/` and `analysis/` are **git-ignored**; the Stockfish binary and all
analysis output are local artifacts, not source. A working engine binary is
present at `engines/stockfish/stockfish`; if it is missing, run `install-engine`.

The tool needs network access for live Chess.com fetches and for `install-engine`;
the `--pgn` and `solve` paths are fully offline. The GUI needs Flask
(`requirements-web.txt`), binds to `127.0.0.1`, serves no third-party assets, and
is offline except for the live-analysis form (which fetches from Chess.com).
