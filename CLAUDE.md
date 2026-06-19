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
python3 blunder_lab.py gui                    # local browser GUI at 127.0.0.1:8000

python3 -m pip install -r requirements-lessons.txt   # optional: zstandard, for the puzzle DB
python3 blunder_lab.py install-puzzles               # download + filter Lichess puzzles -> data/puzzles.sqlite
python3 -m pip install -r requirements-ai.txt        # optional: anthropic, for AI coaching notes
```

AI coaching notes use `ANTHROPIC_API_KEY` (model `claude-haiku-4-5`) when set, a
local Ollama server when `BLAB_AI_PROVIDER=ollama`, and otherwise fall back to
deterministic templates — so the GUI works fully offline without a key.

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

The CLI lives in `blunder_lab.py` (~1500 lines), one module, five subcommands
(`install-engine`, `analyze`, `solve`, `gui`, `install-puzzles`) dispatched from
`main()` to `build_parser()`. The error-analysis layer lives in the `blab/` package
and the GUI in the `web/` package. Logic is plain functions over three dataclasses:
`AnalysisSettings` (run config), `GameSource` (a parsed game + its raw Chess.com
JSON), and `MoveFinding` (one flagged move; also serves as a puzzle record, now also
carrying `category`/`motifs`/`phase` from the classifier). Errors meant for the user
are raised as `UserFacingError` and printed without a traceback.

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

**Error-analysis layer** (`blab/` package, pure python-chess + stdlib).
`classify.py` turns each finding into a named **cause category** + Lichess **motif**
tags + game **phase** (`classify_finding`), using simplified Lichess-tagger heuristics
(`is_en_prise`/`is_fork`/`is_pin_or_skewer`/`is_discovered_attack` + a crude SEE);
`analyze_game` captures the opponent's reply PV and calls it. `profile.py`
(`build_error_profile`) ranks categories by total centipawns lost, capped per finding
(`IMPACT_CAP_CP`) so a few mates don't dominate. `lessons.py` (`build_lesson`) pairs a
curated per-category concept with a drill deck of the user's own puzzles, topped up
with theme-matched Lichess puzzles when thin. `puzzledb.py` builds/queries a local
SQLite of filtered Lichess puzzles (`install-puzzles` streams `lichess_db_puzzle.csv.zst`
via zstandard, filtering by rating + theme). `aiwriter.py` writes a grounded coaching
note (provider-pluggable: anthropic/ollama/template, cached under `~/.blunder_lab/`) —
the model only restates engine-validated facts, never analyses the position.
`progress.py` is an SM-2 spaced-repetition store at `~/.blunder_lab/progress.db` keyed
by FEN + best move; grading records an attempt, and `category_progress`/`due_keys`
drive mastery and due-for-review counts in the GUI.

**Web GUI** (`web/` package; `gui` subcommand lazy-imports Flask). `web/app.py`
imports `blunder_lab` and is **server-authoritative**: legal moves and grading are
scoped to a stored puzzle index (`/api/runs/<id>/puzzles/<i>/legal` and `/grade`)
and load the FEN/best move from disk, so the browser never gets the answer before
submitting. `web/jobs.py` runs analysis on a single background worker thread via
`run_analysis`; `web/engine_pool.py` shares one lock-guarded Stockfish process for
grading and recreates it on `EngineTerminatedError`. Review boards are
server-rendered `chess.svg`; the solver uses vendored **cm-chessboard**
(`web/static/vendor/cm-chessboard/`, MIT code + CC-BY-SA standard pieces, native ES
modules, no build step). Beyond the per-puzzle endpoints, the API serves the error
profile, per-category lessons (own + Lichess-DB drills, due ones first), DB-puzzle
drills (`/api/db/puzzles/<id>/...`), a coaching note per finding, and spaced-repetition
progress; grading records an SR attempt. Run-id inputs are validated against
`analysis_roots()` to reject path traversal. Web deps are isolated in
`requirements-web.txt`. Tests live in `tests/` (Flask `test_client` plus pure-logic
tests for the `blab/` modules; engine-backed tests are guarded by engine availability).

## Outputs and conventions

`analyze` writes a timestamped dir `analysis/<username>_<timestamp>/` containing
`report.md`, `blunders.csv`, `puzzles.csv`, `puzzles.pgn`, and `raw_games.pgn`.

`engines/`, `analysis/`, and `data/` are **git-ignored** (the Stockfish binary,
analysis output, and the few-hundred-MB Lichess puzzle SQLite are local artifacts, not
source); the spaced-repetition DB and AI-note cache live under `~/.blunder_lab/`. A
working engine binary is present at `engines/stockfish/stockfish`; if it is missing,
run `install-engine`.

The tool needs network access for live Chess.com fetches and for `install-engine`;
the `--pgn` and `solve` paths are fully offline. The GUI needs Flask
(`requirements-web.txt`), binds to `127.0.0.1`, serves no third-party assets, and
is offline except for the live-analysis form (which fetches from Chess.com).
