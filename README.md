# Chess Blunder Lab

A small local CLI for turning your Chess.com games into:

- a blunder/mistake/inaccuracy report
- a `puzzles.csv` file for study
- a `puzzles.pgn` file you can import into chess tools
- a `raw_games.pgn` backup of the games that were analyzed

Pass your Chess.com username with `--username` (it is required).

## Setup

`python-chess` is required:

```bash
python3 -m pip install -r requirements.txt
```

Install a local CLI Stockfish binary into this workspace:

```bash
python3 blunder_lab.py install-engine
```

This downloads the current official Stockfish release for your OS/CPU into
`engines/stockfish/`. You can also use your own engine:

```bash
python3 blunder_lab.py analyze --engine /path/to/stockfish
```

## Run

Analyze your recent Chess.com games:

```bash
python3 blunder_lab.py analyze --username your-username
```

Faster smoke test:

```bash
python3 blunder_lab.py analyze --username your-username --max-games 3 --depth 8
```

More careful analysis:

```bash
python3 blunder_lab.py analyze --username your-username --months 5 --max-games 100 --depth 14
```

Only rapid games:

```bash
python3 blunder_lab.py analyze --username your-username --time-class rapid
```

Analyze a local PGN instead of fetching Chess.com:

```bash
python3 blunder_lab.py analyze --username your-username --pgn my_games.pgn
```

## Solve (interactive trainer)

Replay the puzzles from your most recent analysis run, right in the terminal.
The board is drawn from your side, you type a move in SAN (`Nf3`) or UCI
(`g1f3`), and the engine grades it — so a strong alternative still counts, not
only the single top move.

```bash
python3 blunder_lab.py solve
```

It defaults to the newest `analysis/*/puzzles.csv`. Point it at a specific run,
shuffle, or cap the count:

```bash
python3 blunder_lab.py solve --puzzles analysis/your-username_latest/puzzles.csv --shuffle --max 10
```

During a puzzle you can type `hint`, `skip`, or `quit`. Use `--no-engine` to
grade only against the saved best move (no engine needed), or `--accept-cp` to
loosen/tighten how close to best counts as correct (default 30 centipawns).

## Outputs

Each run creates a directory like:

```text
analysis/your-username_20260616_160000/
```

Inside it:

- `report.md` is the human-readable report.
- `blunders.csv` has every move that crossed the configured thresholds.
- `puzzles.csv` has the positions worth solving again.
- `puzzles.pgn` contains puzzle positions with the engine PV.
- `raw_games.pgn` stores the analyzed games.

## Useful Thresholds

Defaults are intentionally beginner-friendly:

- inaccuracy: 75 centipawns
- mistake: 150 centipawns
- blunder: 300 centipawns
- puzzle: 150 centipawns minimum loss
- puzzle eval floor: -50 centipawns (`--puzzle-min-eval-cp`)

The eval floor keeps a position out of `puzzles.csv` when you were already lost
before the mistake, so you drill clean "there was a good move here" tactics
instead of damage control in a hopeless position. Every blunder still shows up
in `report.md` and `blunders.csv`; the floor only gates the puzzle set. Set it
lower (e.g. `--puzzle-min-eval-cp -300`) to include defensive saves.

You can tune them:

```bash
python3 blunder_lab.py analyze \
  --username your-username \
  --mistake-cp 120 \
  --blunder-cp 250 \
  --puzzle-min-loss-cp 120
```

At roughly 500 Elo, the best study loop is usually:

1. Open `report.md`.
2. Replay the top 5 positions.
3. For each one, ask: "Was there a check, capture, or direct threat?"
4. Drill `puzzles.csv` until the best moves look obvious.
