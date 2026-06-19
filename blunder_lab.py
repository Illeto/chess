#!/usr/bin/env python3
"""Find blunders and generate training puzzles from Chess.com games."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, DefaultDict, Dict, Iterable, List, Optional, Sequence, Tuple

import chess
import chess.engine
import chess.pgn

from blab import classify
from blab import profile as error_profile
from blab import puzzledb


APP_NAME = "chess-blunder-lab"
USER_AGENT = f"{APP_NAME}/0.1 (local personal analysis tool)"
CHESSCOM_ARCHIVES_URL = "https://api.chess.com/pub/player/{username}/games/archives"
STOCKFISH_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
)
MATE_SCORE = 100_000
SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass
class AnalysisSettings:
    username: str
    engine_path: Path
    depth: Optional[int]
    movetime_ms: Optional[int]
    threads: Optional[int]
    hash_mb: Optional[int]
    skip_opening_plies: int
    inaccuracy_cp: int
    mistake_cp: int
    blunder_cp: int
    puzzle_min_loss_cp: int
    puzzle_min_eval_cp: int
    max_pv_moves: int


@dataclass
class GameSource:
    game: chess.pgn.Game
    raw_game: Dict[str, object]
    archive_url: str


@dataclass
class MoveFinding:
    kind: str
    game_index: int
    game_date: str
    time_class: str
    url: str
    event: str
    white: str
    black: str
    user_color: str
    ply: int
    move_number: int
    fen: str
    your_move_san: str
    your_move_uci: str
    best_move_san: str
    best_move_uci: str
    loss_cp: int
    eval_before_cp: int
    eval_after_cp: int
    eval_before: str
    eval_after: str
    pv_san: str
    pv_uci: str
    theme: str
    category: str = ""
    motifs: str = ""
    phase: str = ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "install-engine":
            install_engine(args)
            return 0
        if args.command == "analyze":
            analyze_command(args)
            return 0
        if args.command == "solve":
            solve_command(args)
            return 0
        if args.command == "gui":
            gui_command(args)
            return 0
        if args.command == "install-puzzles":
            install_puzzles_command(args)
            return 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 1


class UserFacingError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Chess.com games, analyze your moves with a UCI engine, "
            "and export blunder reports plus puzzle files."
        )
    )
    subparsers = parser.add_subparsers(dest="command")

    install = subparsers.add_parser(
        "install-engine",
        help="download an official Stockfish CLI binary into this workspace",
    )
    install.add_argument(
        "--dest",
        type=Path,
        default=Path("engines/stockfish"),
        help="destination directory for the engine (default: engines/stockfish)",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="replace an existing destination directory",
    )

    analyze = subparsers.add_parser(
        "analyze",
        help="analyze games and create report/puzzle outputs",
    )
    analyze.add_argument(
        "--username", required=True, help="your Chess.com username"
    )
    analyze.add_argument(
        "--engine",
        type=Path,
        default=None,
        help="path to a UCI engine binary such as stockfish",
    )
    analyze.add_argument(
        "--pgn",
        type=Path,
        default=None,
        help="analyze a local PGN file instead of fetching Chess.com games",
    )
    analyze.add_argument(
        "--months",
        type=int,
        default=3,
        help="number of recent Chess.com monthly archives to fetch (default: 3)",
    )
    analyze.add_argument(
        "--since",
        default=None,
        help="oldest archive to include as YYYY-MM; overrides --months lower bound",
    )
    analyze.add_argument(
        "--until",
        default=None,
        help="newest archive to include as YYYY-MM",
    )
    analyze.add_argument(
        "--max-games",
        type=int,
        default=25,
        help="maximum games to analyze after filtering (default: 25)",
    )
    analyze.add_argument(
        "--time-class",
        choices=["bullet", "blitz", "rapid", "daily"],
        default=None,
        help="only analyze this time class",
    )
    analyze.add_argument(
        "--oldest-first",
        action="store_true",
        help="analyze older games first instead of newest first",
    )
    analyze.add_argument(
        "--depth",
        type=int,
        default=10,
        help="Stockfish search depth per position (default: 10)",
    )
    analyze.add_argument(
        "--movetime-ms",
        type=int,
        default=None,
        help="use fixed milliseconds per position instead of depth",
    )
    analyze.add_argument("--threads", type=int, default=None, help="engine threads")
    analyze.add_argument("--hash-mb", type=int, default=None, help="engine hash MB")
    analyze.add_argument(
        "--skip-opening-plies",
        type=int,
        default=8,
        help="ignore the first N half-moves for findings (default: 8)",
    )
    analyze.add_argument(
        "--inaccuracy-cp",
        type=int,
        default=75,
        help="minimum centipawn loss for an inaccuracy (default: 75)",
    )
    analyze.add_argument(
        "--mistake-cp",
        type=int,
        default=150,
        help="minimum centipawn loss for a mistake (default: 150)",
    )
    analyze.add_argument(
        "--blunder-cp",
        type=int,
        default=300,
        help="minimum centipawn loss for a blunder (default: 300)",
    )
    analyze.add_argument(
        "--puzzle-min-loss-cp",
        type=int,
        default=150,
        help="minimum loss to turn a position into a puzzle (default: 150)",
    )
    analyze.add_argument(
        "--puzzle-min-eval-cp",
        type=int,
        default=-50,
        help=(
            "only make a puzzle when your best move keeps the eval at or above "
            "this many centipawns; skips already-lost positions so you drill "
            "clean tactics rather than damage control (default: -50)"
        ),
    )
    analyze.add_argument(
        "--max-pv-moves",
        type=int,
        default=6,
        help="maximum principal-variation moves saved per puzzle (default: 6)",
    )
    analyze.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for outputs (default: analysis/<username>_<timestamp>)",
    )

    solve = subparsers.add_parser(
        "solve",
        help="interactively solve the puzzles from a previous analyze run",
    )
    solve.add_argument(
        "--puzzles",
        type=Path,
        default=None,
        help="path to a puzzles.csv (default: newest analysis/*/puzzles.csv)",
    )
    solve.add_argument(
        "--engine",
        type=Path,
        default=None,
        help="UCI engine used to grade your move (default: auto-detect)",
    )
    solve.add_argument(
        "--no-engine",
        action="store_true",
        help="grade only against the saved best move, without launching an engine",
    )
    solve.add_argument(
        "--depth",
        type=int,
        default=12,
        help="engine search depth when grading your move (default: 12)",
    )
    solve.add_argument(
        "--accept-cp",
        type=int,
        default=30,
        help=(
            "count your move correct if it loses at most this many centipawns "
            "versus the engine's best move (default: 30)"
        ),
    )
    solve.add_argument(
        "--max",
        type=int,
        default=None,
        dest="max_puzzles",
        help="attempt at most this many puzzles",
    )
    solve.add_argument(
        "--shuffle",
        action="store_true",
        help="shuffle the puzzle order",
    )

    gui = subparsers.add_parser(
        "gui",
        help="launch the local web GUI (review blunders and solve in a browser)",
    )
    gui.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    gui.add_argument(
        "--port",
        type=int,
        default=8000,
        help="bind port (default: 8000; avoids macOS AirPlay Receiver on 5000)",
    )
    gui.add_argument(
        "--no-open",
        action="store_true",
        help="do not open a browser window automatically",
    )

    puzzles = subparsers.add_parser(
        "install-puzzles",
        help="download + build the local Lichess puzzle DB for lesson top-ups",
    )
    puzzles.add_argument(
        "--max-rating",
        type=int,
        default=puzzledb.DEFAULT_MAX_RATING,
        help=f"keep puzzles rated <= this (default: {puzzledb.DEFAULT_MAX_RATING})",
    )
    puzzles.add_argument(
        "--db",
        type=Path,
        default=None,
        help="output SQLite path (default: data/puzzles.sqlite)",
    )

    return parser


def install_engine(args: argparse.Namespace) -> None:
    dest = args.dest.expanduser().resolve()
    if dest.exists():
        if not args.force:
            existing = find_local_engine(dest)
            if existing:
                print(f"Engine already installed: {existing}")
                return
            raise UserFacingError(
                f"{dest} already exists. Use --force to replace it."
            )
        shutil.rmtree(dest)

    dest.mkdir(parents=True, exist_ok=True)
    release = fetch_json(STOCKFISH_LATEST_RELEASE_URL)
    tag = str(release.get("tag_name", "latest"))
    asset_name = stockfish_asset_name()
    assets = release.get("assets", [])
    asset = next((item for item in assets if item.get("name") == asset_name), None)
    if not asset:
        names = ", ".join(str(item.get("name")) for item in assets)
        raise UserFacingError(
            f"Could not find a Stockfish asset named {asset_name!r}. "
            f"Available assets: {names}"
        )

    url = str(asset["browser_download_url"])
    archive_path = dest / asset_name
    print(f"Downloading {asset_name} from official-stockfish/Stockfish {tag}...")
    download_file(url, archive_path)

    extract_dir = dest / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            safe_extract_zip(zf, extract_dir)
    else:
        with tarfile.open(archive_path) as tf:
            safe_extract_tar(tf, extract_dir)

    engine = choose_engine_binary(extract_dir)
    if not engine:
        raise UserFacingError(f"Could not find a Stockfish binary in {archive_path}.")

    engine.chmod(engine.stat().st_mode | 0o755)
    link = dest / "stockfish"
    if link.exists() or link.is_symlink():
        link.unlink()
    try:
        link.symlink_to(engine)
    except OSError:
        shutil.copy2(engine, link)
        link.chmod(link.stat().st_mode | 0o755)

    remove_quarantine(link)
    test_uci_engine(link)
    (dest / "ENGINE.txt").write_text(
        f"Stockfish release: {tag}\n"
        f"Asset: {asset_name}\n"
        f"Source: {url}\n"
        f"Binary: {engine}\n",
        encoding="utf-8",
    )
    print(f"Installed engine: {link}")


def analyze_command(args: argparse.Namespace) -> None:
    username = args.username
    engine_path = resolve_engine(args.engine)
    output_dir = args.output_dir or default_output_dir(username)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = AnalysisSettings(
        username=username,
        engine_path=engine_path,
        depth=None if args.movetime_ms else args.depth,
        movetime_ms=args.movetime_ms,
        threads=args.threads,
        hash_mb=args.hash_mb,
        skip_opening_plies=args.skip_opening_plies,
        inaccuracy_cp=args.inaccuracy_cp,
        mistake_cp=args.mistake_cp,
        blunder_cp=args.blunder_cp,
        puzzle_min_loss_cp=args.puzzle_min_loss_cp,
        puzzle_min_eval_cp=args.puzzle_min_eval_cp,
        max_pv_moves=args.max_pv_moves,
    )

    if args.pgn:
        games = load_local_pgn(args.pgn, username)
        raw_pgn = args.pgn.read_text(encoding="utf-8")
        (output_dir / "raw_games.pgn").write_text(raw_pgn, encoding="utf-8")
    else:
        games = fetch_chesscom_sources(
            username=username,
            months=args.months,
            since=args.since,
            until=args.until,
            max_games=args.max_games,
            time_class=args.time_class,
            newest_first=not args.oldest_first,
        )
        write_raw_games_pgn(games, output_dir / "raw_games.pgn")

    if not games:
        raise UserFacingError("No games matched the requested filters.")

    print(f"Analyzing {len(games)} game(s) with {engine_path}...")

    def cli_progress(phase: str, done: int, total: int, label: str) -> None:
        if phase == "analyzing":
            print(f"  {done:>3}/{total} {label}")

    run_analysis(settings, games, output_dir, progress_cb=cli_progress)

    print()
    print(f"Report:  {output_dir / 'report.md'}")
    print(f"CSV:     {output_dir / 'blunders.csv'}")
    print(f"Puzzles: {output_dir / 'puzzles.csv'}")
    print(f"PGN:     {output_dir / 'puzzles.pgn'}")


def run_analysis(
    settings: AnalysisSettings,
    sources: Sequence[GameSource],
    output_dir: Path,
    progress_cb: Optional[Callable[[str, int, int, str], None]] = None,
) -> Tuple[List[MoveFinding], List[MoveFinding]]:
    """Run the engine over already-fetched games and write all analysis outputs.

    ``progress_cb(phase, done, total, label)`` is called with phase in
    {"analyzing", "writing", "done"}. Fetching games and writing raw_games.pgn
    are the caller's responsibility (they differ between the CLI and the GUI).
    Opens its own engine process, so callers can run several concurrently.
    """
    findings: List[MoveFinding] = []
    puzzles: List[MoveFinding] = []
    started = time.time()
    total = len(sources)

    try:
        with chess.engine.SimpleEngine.popen_uci(str(settings.engine_path)) as engine:
            configure_engine(engine, settings)
            limit = engine_limit(settings)
            for index, source in enumerate(sources, start=1):
                game_findings, game_puzzles = analyze_game(
                    source=source,
                    game_index=index,
                    settings=settings,
                    engine=engine,
                    limit=limit,
                )
                findings.extend(game_findings)
                puzzles.extend(game_puzzles)
                if progress_cb is not None:
                    progress_cb(
                        "analyzing",
                        index,
                        total,
                        f"{game_label(source.game)}: "
                        f"{len(game_findings)} finding(s), {len(game_puzzles)} puzzle(s)",
                    )
    except chess.engine.EngineError as exc:
        raise UserFacingError(f"Engine error: {exc}") from exc
    except FileNotFoundError as exc:
        raise UserFacingError(f"Engine not found: {settings.engine_path}") from exc

    if progress_cb is not None:
        progress_cb("writing", total, total, "writing outputs")
    write_findings_csv(findings, output_dir / "blunders.csv")
    write_findings_csv(puzzles, output_dir / "puzzles.csv")
    write_puzzles_pgn(puzzles, output_dir / "puzzles.pgn")
    write_report(
        settings=settings,
        games=sources,
        findings=findings,
        puzzles=puzzles,
        elapsed_seconds=time.time() - started,
        output_path=output_dir / "report.md",
    )
    if progress_cb is not None:
        progress_cb("done", total, total, "done")
    return findings, puzzles


def resolve_engine(explicit: Optional[Path]) -> Path:
    if explicit:
        engine = explicit.expanduser().resolve()
        if not engine.exists():
            raise UserFacingError(f"Engine path does not exist: {engine}")
        return engine

    env_path = os.environ.get("STOCKFISH_EXECUTABLE")
    if env_path:
        engine = Path(env_path).expanduser().resolve()
        if engine.exists():
            return engine

    which = shutil.which("stockfish")
    if which:
        return Path(which).resolve()

    for root in local_engine_roots():
        local = find_local_engine(root)
        if local:
            return local.resolve()

    raise UserFacingError(
        "No Stockfish CLI binary found. Run:\n"
        "  python3 blunder_lab.py install-engine\n"
        "Then run analyze again, or pass --engine /path/to/stockfish."
    )


def local_engine_roots() -> List[Path]:
    roots = [Path("engines/stockfish").resolve()]
    script_root = (SCRIPT_DIR / "engines/stockfish").resolve()
    if script_root not in roots:
        roots.append(script_root)
    return roots


def find_local_engine(root: Path) -> Optional[Path]:
    direct = root / "stockfish"
    if direct.exists() and os.access(direct, os.X_OK):
        return direct
    if not root.exists():
        return None
    return choose_engine_binary(root)


def choose_engine_binary(root: Path) -> Optional[Path]:
    candidates: List[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if "stockfish" not in name:
            continue
        if path.suffix.lower() in {".txt", ".md", ".nnue", ".json", ".tar", ".zip"}:
            continue
        if sys.platform == "win32" and path.suffix.lower() != ".exe":
            continue
        candidates.append(path)

    if not candidates:
        return None

    machine = platform.machine().lower()
    preferred_terms = []
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        preferred_terms = ["m1", "apple", "arm64"]
    elif machine in {"x86_64", "amd64"}:
        preferred_terms = ["x86-64", "x86_64"]

    def score(path: Path) -> Tuple[int, int]:
        text = str(path).lower()
        preferred = sum(1 for term in preferred_terms if term in text)
        return preferred, -len(path.parts)

    chosen = max(candidates, key=score)
    chosen.chmod(chosen.stat().st_mode | 0o755)
    return chosen


def stockfish_asset_name() -> str:
    system = sys.platform
    machine = platform.machine().lower()

    if system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "stockfish-macos-m1-apple-silicon.tar"
        return "stockfish-macos-x86-64.tar"
    if system.startswith("linux"):
        return "stockfish-ubuntu-x86-64.tar"
    if system == "win32":
        return "stockfish-windows-x86-64.zip"

    raise UserFacingError(
        f"Unsupported platform for automatic Stockfish download: {system}/{machine}. "
        "Download Stockfish manually and pass --engine."
    )


def test_uci_engine(engine: Path) -> None:
    proc = subprocess.run(
        [str(engine)],
        input="uci\nisready\nquit\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0 or "uciok" not in proc.stdout or "readyok" not in proc.stdout:
        raise UserFacingError(
            f"Downloaded engine did not respond as UCI.\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )


def remove_quarantine(path: Path) -> None:
    if sys.platform != "darwin":
        return
    xattr = shutil.which("xattr")
    if not xattr:
        return
    subprocess.run(
        [xattr, "-dr", "com.apple.quarantine", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def fetch_chesscom_sources(
    username: str,
    months: Optional[int],
    since: Optional[str],
    until: Optional[str],
    max_games: Optional[int],
    time_class: Optional[str],
    newest_first: bool,
) -> List[GameSource]:
    archives = fetch_archives(username)
    archives = filter_archives(archives, months=months, since=since, until=until)
    sources: List[GameSource] = []

    for archive_url in archives:
        data = fetch_json(archive_url)
        for raw in data.get("games", []):
            if time_class and raw.get("time_class") != time_class:
                continue
            pgn_text = raw.get("pgn")
            if not isinstance(pgn_text, str) or not pgn_text.strip():
                continue
            game = chess.pgn.read_game(io.StringIO(pgn_text))
            if game is None:
                continue
            if not is_user_game(game, username):
                continue
            sources.append(GameSource(game=game, raw_game=raw, archive_url=archive_url))

    sources.sort(
        key=lambda source: int(source.raw_game.get("end_time") or 0),
        reverse=newest_first,
    )
    if max_games:
        sources = sources[:max_games]
    return sources


def fetch_archives(username: str) -> List[str]:
    url = CHESSCOM_ARCHIVES_URL.format(username=username)
    data = fetch_json(url)
    archives = data.get("archives")
    if not isinstance(archives, list):
        raise UserFacingError(f"No archives returned for Chess.com user {username!r}.")
    return [str(item) for item in archives]


def filter_archives(
    archives: List[str],
    months: Optional[int],
    since: Optional[str],
    until: Optional[str],
) -> List[str]:
    def ym(url: str) -> str:
        parts = url.rstrip("/").split("/")
        return f"{parts[-2]}-{parts[-1]}"

    filtered = archives
    if since:
        validate_ym(since)
        filtered = [url for url in filtered if ym(url) >= since]
    if until:
        validate_ym(until)
        filtered = [url for url in filtered if ym(url) <= until]
    if months and not since:
        filtered = filtered[-months:]
    return filtered


def validate_ym(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise UserFacingError(f"Expected YYYY-MM, got {value!r}.") from exc


def fetch_json(url: str) -> Dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UserFacingError(f"HTTP {exc.code} while fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise UserFacingError(f"Could not fetch {url}: {exc.reason}") from exc


def download_file(url: str, output_path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        with output_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def safe_extract_tar(archive: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in archive.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest) + os.sep):
            raise UserFacingError(f"Refusing unsafe tar path: {member.name}")
    archive.extractall(dest)


def safe_extract_zip(archive: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in archive.infolist():
        target = (dest / member.filename).resolve()
        if not str(target).startswith(str(dest) + os.sep):
            raise UserFacingError(f"Refusing unsafe zip path: {member.filename}")
    archive.extractall(dest)


def load_local_pgn(path: Path, username: str) -> List[GameSource]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise UserFacingError(f"PGN file does not exist: {path}")

    sources: List[GameSource] = []
    with path.open(encoding="utf-8") as handle:
        while True:
            game = chess.pgn.read_game(handle)
            if game is None:
                break
            if is_user_game(game, username):
                sources.append(
                    GameSource(game=game, raw_game={}, archive_url=f"file://{path}")
                )
    return sources


def is_user_game(game: chess.pgn.Game, username: str) -> bool:
    user = username.lower()
    return game.headers.get("White", "").lower() == user or game.headers.get(
        "Black", ""
    ).lower() == user


def configure_engine(
    engine: chess.engine.SimpleEngine, settings: AnalysisSettings
) -> None:
    options = {}
    if settings.threads is not None and "Threads" in engine.options:
        options["Threads"] = settings.threads
    if settings.hash_mb is not None and "Hash" in engine.options:
        options["Hash"] = settings.hash_mb
    if options:
        engine.configure(options)


def engine_limit(settings: AnalysisSettings) -> chess.engine.Limit:
    if settings.movetime_ms:
        return chess.engine.Limit(time=settings.movetime_ms / 1000)
    return chess.engine.Limit(depth=settings.depth)


def analyze_game(
    source: GameSource,
    game_index: int,
    settings: AnalysisSettings,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
) -> Tuple[List[MoveFinding], List[MoveFinding]]:
    game = source.game
    username = settings.username.lower()
    white = game.headers.get("White", "")
    black = game.headers.get("Black", "")
    if white.lower() == username:
        user_color = chess.WHITE
        user_color_name = "White"
    elif black.lower() == username:
        user_color = chess.BLACK
        user_color_name = "Black"
    else:
        return [], []

    findings: List[MoveFinding] = []
    puzzles: List[MoveFinding] = []
    board = game.board()

    for ply, move in enumerate(game.mainline_moves(), start=1):
        moving_color = board.turn
        move_san = board.san(move)
        should_analyze = (
            moving_color == user_color and ply > settings.skip_opening_plies
        )

        if not should_analyze:
            board.push(move)
            continue

        before_board = board.copy(stack=False)
        before_info = engine.analyse(before_board, limit)
        best_move = first_pv_move(before_info)
        if best_move is None:
            board.push(move)
            continue
        if best_move == move:
            board.push(move)
            continue

        before_cp, before_text = score_for_color(before_info, moving_color)
        pv_moves = pv_from_info(before_info, settings.max_pv_moves)
        pv_san = pv_to_san(before_board, pv_moves)
        pv_uci = " ".join(item.uci() for item in pv_moves)
        best_move_san = before_board.san(best_move)

        board.push(move)
        after_board = board.copy(stack=False)
        after_pv: List[chess.Move] = []
        terminal = terminal_score(board, moving_color)
        if terminal:
            after_cp, after_text = terminal
        else:
            after_info = engine.analyse(board, limit)
            after_cp, after_text = score_for_color(after_info, moving_color)
            after_pv = pv_from_info(after_info, settings.max_pv_moves)
        loss_cp = max(0, before_cp - after_cp)
        kind = classify_loss(loss_cp, settings)
        if not kind:
            continue

        category, motif_list, phase = classify.classify_finding(
            before_board=before_board,
            your_move=move,
            best_move=best_move,
            before_pv=pv_moves,
            after_board=after_board,
            after_pv=after_pv,
            eval_before_cp=before_cp,
            eval_after_cp=after_cp,
            user_color=moving_color,
            move_number=before_board.fullmove_number,
        )

        finding = MoveFinding(
            kind=kind,
            game_index=game_index,
            game_date=game_date(source),
            time_class=str(source.raw_game.get("time_class") or game.headers.get("TimeControl", "")),
            url=str(source.raw_game.get("url") or game.headers.get("Link", "")),
            event=game.headers.get("Event", ""),
            white=white,
            black=black,
            user_color=user_color_name,
            ply=ply,
            move_number=before_board.fullmove_number,
            fen=before_board.fen(),
            your_move_san=move_san,
            your_move_uci=move.uci(),
            best_move_san=best_move_san,
            best_move_uci=best_move.uci(),
            loss_cp=loss_cp,
            eval_before_cp=before_cp,
            eval_after_cp=after_cp,
            eval_before=before_text,
            eval_after=after_text,
            pv_san=pv_san,
            pv_uci=pv_uci,
            theme=detect_theme(before_board, best_move, before_info),
            category=category,
            motifs=", ".join(motif_list),
            phase=phase,
        )
        findings.append(finding)

        is_clean_puzzle = (
            loss_cp >= settings.puzzle_min_loss_cp
            and best_move != move
            and before_cp >= settings.puzzle_min_eval_cp
        )
        if is_clean_puzzle:
            puzzles.append(finding)

    return findings, puzzles


def first_pv_move(info: Dict[str, object]) -> Optional[chess.Move]:
    pv = info.get("pv")
    if isinstance(pv, list) and pv:
        return pv[0]
    return None


def pv_from_info(info: Dict[str, object], max_moves: int) -> List[chess.Move]:
    pv = info.get("pv")
    if not isinstance(pv, list):
        return []
    return [move for move in pv[:max_moves] if isinstance(move, chess.Move)]


def score_for_color(info: Dict[str, object], color: chess.Color) -> Tuple[int, str]:
    pov_score = info.get("score")
    if not isinstance(pov_score, chess.engine.PovScore):
        return 0, "?"

    score = pov_score.pov(color)
    mate = score.mate()
    if mate is not None:
        cp = MATE_SCORE if mate >= 0 else -MATE_SCORE
        return cp, f"M{mate:+d}"

    cp = score.score(mate_score=MATE_SCORE)
    if cp is None:
        return 0, "?"
    return int(cp), format_cp(cp)


def format_cp(cp: int) -> str:
    return f"{cp / 100:+.2f}"


def terminal_score(board: chess.Board, color: chess.Color) -> Optional[Tuple[int, str]]:
    if not board.is_game_over(claim_draw=False):
        return None

    outcome = board.outcome(claim_draw=False)
    if outcome is None or outcome.winner is None:
        return 0, "draw"
    if outcome.winner == color:
        return MATE_SCORE, "M+0"
    return -MATE_SCORE, "M-0"


def format_loss(cp: int) -> str:
    if cp >= 10_000:
        return "mate swing"
    return f"{cp / 100:.2f}"


def loss_phrase(cp: int) -> str:
    if cp >= 10_000:
        return "mate swing"
    return f"{format_loss(cp)} pawns"


def classify_loss(loss_cp: int, settings: AnalysisSettings) -> Optional[str]:
    if loss_cp >= settings.blunder_cp:
        return "blunder"
    if loss_cp >= settings.mistake_cp:
        return "mistake"
    if loss_cp >= settings.inaccuracy_cp:
        return "inaccuracy"
    return None


def detect_theme(
    board: chess.Board, move: chess.Move, info: Dict[str, object]
) -> str:
    themes: List[str] = []
    board_after = board.copy(stack=False)

    if board.is_capture(move):
        themes.append("capture")
    if board.gives_check(move):
        themes.append("check")
    if move.promotion:
        themes.append("promotion")
    if board.is_castling(move):
        themes.append("castling")

    board_after.push(move)
    if board_after.is_checkmate():
        themes.append("mate")
    elif score_text_has_mate(info):
        themes.append("mate threat")

    if attacks_high_value_piece(board_after, not board.turn):
        themes.append("attacks queen/rook")

    return ", ".join(dict.fromkeys(themes)) or "best move"


def score_text_has_mate(info: Dict[str, object]) -> bool:
    pov_score = info.get("score")
    if not isinstance(pov_score, chess.engine.PovScore):
        return False
    return pov_score.white().mate() is not None or pov_score.black().mate() is not None


def attacks_high_value_piece(board: chess.Board, attacked_color: chess.Color) -> bool:
    for square, piece in board.piece_map().items():
        if piece.color != attacked_color:
            continue
        if piece.piece_type not in {chess.QUEEN, chess.ROOK}:
            continue
        if board.is_attacked_by(not attacked_color, square):
            return True
    return False


def pv_to_san(board: chess.Board, pv: Iterable[chess.Move]) -> str:
    temp = board.copy(stack=False)
    parts: List[str] = []
    for move in pv:
        if move not in temp.legal_moves:
            break
        parts.append(temp.san(move))
        temp.push(move)
    return " ".join(parts)


def game_date(source: GameSource) -> str:
    raw_end = source.raw_game.get("end_time")
    if isinstance(raw_end, int):
        return datetime.fromtimestamp(raw_end, timezone.utc).strftime("%Y-%m-%d")
    utc_date = source.game.headers.get("UTCDate")
    if utc_date:
        return utc_date.replace(".", "-")
    return source.game.headers.get("Date", "????.??.??").replace(".", "-")


def game_label(game: chess.pgn.Game) -> str:
    white = game.headers.get("White", "?")
    black = game.headers.get("Black", "?")
    date = game.headers.get("UTCDate") or game.headers.get("Date") or "?"
    return f"{date} {white}-{black}"


def write_raw_games_pgn(sources: Sequence[GameSource], output_path: Path) -> None:
    chunks = []
    for source in sources:
        pgn = source.raw_game.get("pgn")
        if isinstance(pgn, str):
            chunks.append(pgn.strip())
        else:
            exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
            chunks.append(source.game.accept(exporter).strip())
    output_path.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")


def write_findings_csv(findings: Sequence[MoveFinding], output_path: Path) -> None:
    fieldnames = [
        "kind",
        "game_index",
        "game_date",
        "time_class",
        "url",
        "white",
        "black",
        "user_color",
        "move_number",
        "ply",
        "fen",
        "your_move_san",
        "your_move_uci",
        "best_move_san",
        "best_move_uci",
        "loss_cp",
        "eval_before_cp",
        "eval_after_cp",
        "eval_before",
        "eval_after",
        "pv_san",
        "pv_uci",
        "theme",
        "category",
        "motifs",
        "phase",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for finding in findings:
            writer.writerow({name: getattr(finding, name) for name in fieldnames})


def write_puzzles_pgn(puzzles: Sequence[MoveFinding], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        for index, puzzle in enumerate(puzzles, start=1):
            board = chess.Board(puzzle.fen)
            game = chess.pgn.Game()
            game.setup(board)
            game.headers["Event"] = f"{APP_NAME} Puzzle {index}"
            game.headers["Site"] = puzzle.url or "?"
            game.headers["Date"] = puzzle.game_date.replace("-", ".")
            game.headers["Round"] = "-"
            game.headers["White"] = puzzle.white
            game.headers["Black"] = puzzle.black
            game.headers["Result"] = "*"
            game.headers["Annotator"] = APP_NAME

            node = game
            moves = [
                chess.Move.from_uci(uci)
                for uci in puzzle.pv_uci.split()
                if uci.strip()
            ]
            if not moves:
                moves = [chess.Move.from_uci(puzzle.best_move_uci)]
            for move in moves:
                if move not in board.legal_moves:
                    break
                node = node.add_variation(move)
                board.push(move)

            exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
            handle.write(game.accept(exporter))
            handle.write("\n\n")


def study_focus_lines(
    findings: Sequence[MoveFinding],
    puzzles: Sequence[MoveFinding],
    settings: AnalysisSettings,
) -> List[str]:
    if not findings:
        return []

    lines = [
        "## Study Focus",
        "",
        (
            "- Puzzle filter: positions are included when the missed move lost at "
            f"least {format_loss(settings.puzzle_min_loss_cp)} pawns and the best "
            f"move kept the eval at {format_cp(settings.puzzle_min_eval_cp)} or better."
        ),
    ]

    themes = Counter()
    for finding in findings:
        themes.update(split_themes(finding.theme))
    if themes:
        formatted = ", ".join(
            f"{theme} ({count})" for theme, count in themes.most_common(5)
        )
        lines.append(f"- Most repeated themes: {formatted}.")

    game_rows = summarize_games(findings, puzzles)
    if game_rows:
        lines.append("- Games to review first:")
        for row in game_rows[:5]:
            label = f"{row['date']} {row['white']} vs {row['black']}"
            counts = (
                f"{row['findings']} finding(s), {row['blunders']} blunder(s), "
                f"{row['puzzles']} puzzle(s)"
            )
            if row["url"]:
                lines.append(f"  - {label}: {counts} - {row['url']}")
            else:
                lines.append(f"  - {label}: {counts}")

    lines.append("")
    return lines


def split_themes(theme: str) -> List[str]:
    parts = [part.strip() for part in theme.split(",") if part.strip()]
    return parts or ["best move"]


def summarize_games(
    findings: Sequence[MoveFinding], puzzles: Sequence[MoveFinding]
) -> List[Dict[str, object]]:
    rows: DefaultDict[Tuple[int, str, str, str, str], Dict[str, object]] = defaultdict(
        lambda: {
            "findings": 0,
            "blunders": 0,
            "mistakes": 0,
            "inaccuracies": 0,
            "puzzles": 0,
            "date": "",
            "white": "",
            "black": "",
            "url": "",
        }
    )

    for finding in findings:
        row = rows[game_key(finding)]
        row["date"] = finding.game_date
        row["white"] = finding.white
        row["black"] = finding.black
        row["url"] = finding.url
        row["findings"] = int(row["findings"]) + 1
        if finding.kind == "blunder":
            row["blunders"] = int(row["blunders"]) + 1
        elif finding.kind == "mistake":
            row["mistakes"] = int(row["mistakes"]) + 1
        elif finding.kind == "inaccuracy":
            row["inaccuracies"] = int(row["inaccuracies"]) + 1

    for puzzle in puzzles:
        rows[game_key(puzzle)]["puzzles"] = int(rows[game_key(puzzle)]["puzzles"]) + 1

    return sorted(
        rows.values(),
        key=lambda row: (
            int(row["blunders"]),
            int(row["mistakes"]),
            int(row["findings"]),
            int(row["puzzles"]),
        ),
        reverse=True,
    )


def game_key(finding: MoveFinding) -> Tuple[int, str, str, str, str]:
    return (
        finding.game_index,
        finding.game_date,
        finding.white,
        finding.black,
        finding.url,
    )


def write_report(
    settings: AnalysisSettings,
    games: Sequence[GameSource],
    findings: Sequence[MoveFinding],
    puzzles: Sequence[MoveFinding],
    elapsed_seconds: float,
    output_path: Path,
) -> None:
    counts = {"inaccuracy": 0, "mistake": 0, "blunder": 0}
    for finding in findings:
        counts[finding.kind] = counts.get(finding.kind, 0) + 1

    lines = [
        f"# {settings.username} Blunder Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Games analyzed: {len(games)}",
        f"Engine: `{settings.engine_path}`",
        f"Limit: {limit_description(settings)}",
        f"Skipped opening plies: {settings.skip_opening_plies}",
        f"Runtime: {elapsed_seconds:.1f}s",
        "",
        "## Summary",
        "",
        f"- Inaccuracies: {counts.get('inaccuracy', 0)}",
        f"- Mistakes: {counts.get('mistake', 0)}",
        f"- Blunders: {counts.get('blunder', 0)}",
        f"- Training puzzles: {len(puzzles)}",
        "",
    ]

    profile = error_profile.build_error_profile(
        {
            "category": f.category,
            "motifs": f.motifs,
            "phase": f.phase,
            "loss_cp": f.loss_cp,
        }
        for f in findings
    )
    lines.extend(error_profile.format_profile_lines(profile))
    lines.extend(study_focus_lines(findings, puzzles, settings))
    lines.extend(["## Top Findings", ""])

    top = sorted(findings, key=lambda item: item.loss_cp, reverse=True)[:25]
    if not top:
        lines.append("No findings crossed the configured thresholds.")
    for index, finding in enumerate(top, start=1):
        color_move = f"{finding.move_number}{'.' if finding.user_color == 'White' else '...'}"
        lines.extend(
            [
                f"### {index}. {finding.kind.title()} on {color_move} {finding.your_move_san}",
                "",
                f"- Game: {finding.game_date} `{finding.white}` vs `{finding.black}`",
                f"- Loss: {loss_phrase(finding.loss_cp)} "
                f"({finding.eval_before} -> {finding.eval_after})",
                f"- Best move: `{finding.best_move_san}`",
                f"- PV: `{finding.pv_san or finding.best_move_san}`",
                f"- Theme: {finding.theme}",
                f"- FEN: `{finding.fen}`",
            ]
        )
        if finding.url:
            lines.append(f"- Link: {finding.url}")
        lines.append("")

    lines.extend(
        [
            "## How To Study These",
            "",
            "Fastest: solve them interactively in your terminal (it grades each move "
            "with the engine, so good alternatives also count):",
            "",
            "```bash",
            f"python3 blunder_lab.py solve --puzzles {output_path.parent / 'puzzles.csv'}",
            "```",
            "",
            "Or do it by hand:",
            "",
            "1. Open `puzzles.csv` and hide the `best_move_san` column.",
            "2. Paste the FEN into a board, choose your move, then reveal the answer.",
            "3. After solving, ask why the best move works: check, capture, threat, or mate.",
            "4. Revisit the biggest blunders first; those are usually the fastest rating gains.",
            "",
        ]
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")


def limit_description(settings: AnalysisSettings) -> str:
    if settings.movetime_ms:
        return f"{settings.movetime_ms}ms per position"
    return f"depth {settings.depth}"


def default_output_dir(username: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("analysis") / f"{username}_{stamp}"


def gui_command(args: argparse.Namespace) -> None:
    try:
        import flask  # noqa: F401
    except ImportError as exc:
        raise UserFacingError(
            "The GUI needs Flask. Install the web dependencies with:\n"
            "  python3 -m pip install -r requirements-web.txt"
        ) from exc

    from web import engine_pool
    from web.app import create_app

    app = create_app()
    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Chess Blunder Lab GUI running at {url}  (press Ctrl-C to stop)")
    try:
        app.run(host=args.host, port=args.port, use_reloader=False, threaded=True)
    finally:
        engine_pool.close()


def install_puzzles_command(args: argparse.Namespace) -> None:
    try:
        import zstandard  # noqa: F401
    except ImportError as exc:
        raise UserFacingError(
            "install-puzzles needs zstandard. Install it with:\n"
            "  python3 -m pip install -r requirements-lessons.txt"
        ) from exc

    db_path = (args.db or puzzledb.default_db_path()).expanduser()
    print(f"Building Lichess puzzle DB (rating <= {args.max_rating}) at {db_path}")
    print("Streaming ~250 MB from database.lichess.org; this can take a few minutes...")

    def progress(scanned: int, kept: int) -> None:
        print(f"  scanned {scanned:,}  kept {kept:,}", flush=True)

    kept = puzzledb.download_and_build(
        db_path=db_path, max_rating=args.max_rating, progress_cb=progress
    )
    print(f"Done. Kept {kept:,} puzzles -> {db_path}")


def solve_command(args: argparse.Namespace) -> None:
    puzzles_path = args.puzzles
    if puzzles_path is None:
        puzzles_path = latest_puzzles_csv()
        if puzzles_path is None:
            raise UserFacingError(
                "No puzzles.csv found under analysis/. Run an analyze first, "
                "or pass --puzzles path/to/puzzles.csv."
            )
    puzzles_path = puzzles_path.expanduser().resolve()
    if not puzzles_path.exists():
        raise UserFacingError(f"Puzzle file does not exist: {puzzles_path}")

    rows = load_puzzle_rows(puzzles_path)
    if not rows:
        raise UserFacingError(f"No puzzles found in {puzzles_path}.")
    if args.shuffle:
        random.shuffle(rows)
    if args.max_puzzles:
        rows = rows[: args.max_puzzles]

    engine: Optional[chess.engine.SimpleEngine] = None
    if not args.no_engine:
        try:
            engine_path = resolve_engine(args.engine)
            engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
        except (UserFacingError, chess.engine.EngineError, FileNotFoundError):
            print(
                "No usable engine found; grading against the saved best move only.\n",
                file=sys.stderr,
            )
            engine = None

    limit = chess.engine.Limit(depth=args.depth)
    print(f"Loaded {len(rows)} puzzle(s) from {puzzles_path}")
    print("Enter moves as SAN (Nf3) or UCI (g1f3). Commands: hint, skip, quit.\n")

    correct = 0
    attempted = 0
    skipped = 0
    try:
        for index, row in enumerate(rows, start=1):
            outcome = solve_one(
                row, index, len(rows), engine, limit, args.accept_cp
            )
            if outcome == "quit":
                break
            if outcome == "skip":
                skipped += 1
                continue
            attempted += 1
            if outcome == "correct":
                correct += 1
    finally:
        if engine is not None:
            engine.quit()

    print()
    accuracy = f"{(correct / attempted * 100):.0f}%" if attempted else "n/a"
    print(
        f"Solved {correct}/{attempted} ({accuracy}); "
        f"{skipped} skipped of {len(rows)} total."
    )


def solve_one(
    row: Dict[str, str],
    index: int,
    total: int,
    engine: Optional[chess.engine.SimpleEngine],
    limit: chess.engine.Limit,
    accept_cp: int,
) -> str:
    fen = (row.get("fen") or "").strip()
    try:
        board = chess.Board(fen)
    except ValueError:
        print(f"[{index}/{total}] Skipping puzzle with an invalid FEN.")
        return "skip"

    user_color = board.turn
    color_name = "White" if user_color == chess.WHITE else "Black"
    best_uci = (row.get("best_move_uci") or "").strip()
    best_san = (row.get("best_move_san") or "").strip()
    pv_san = (row.get("pv_san") or "").strip() or best_san
    theme = (row.get("theme") or "").strip()

    print(f"Puzzle {index}/{total} - you are {color_name}, to move")
    print(render_board(board, user_color))
    if theme and theme != "best move":
        print(f"Theme: {theme}")

    move: Optional[chess.Move] = None
    while move is None:
        try:
            raw = input("Your move: ").strip()
        except EOFError:
            print()
            return "quit"
        if not raw:
            continue
        low = raw.lower()
        if low in {"quit", "q"}:
            return "quit"
        if low in {"skip", "s"}:
            print(f"  Skipped. Best was {best_san or best_uci}.\n")
            return "skip"
        if low in {"hint", "h"}:
            print(hint_for(board, best_uci))
            continue
        move = parse_move(board, raw)
        if move is None:
            print("  Not a legal move here. Try again (e.g. Nf3 or g1f3).")

    your_san = safe_san(board, move)
    correct, detail = grade_move(board, move, best_uci, engine, limit, accept_cp)
    mark = "OK" if correct else "NO"
    print(f"  [{mark}] {your_san} - {detail}")
    if not correct or your_san != best_san:
        print(f"  Best: {best_san or best_uci}" + (f"  ({pv_san})" if pv_san else ""))
    print()
    return "correct" if correct else "wrong"


def grade_move(
    board: chess.Board,
    move: chess.Move,
    best_uci: str,
    engine: Optional[chess.engine.SimpleEngine],
    limit: chess.engine.Limit,
    accept_cp: int,
) -> Tuple[bool, str]:
    if engine is None:
        if best_uci and move.uci() == best_uci:
            return True, "matches the saved best move."
        return False, f"the saved best move was {best_uci or '(unknown)'}."

    color = board.turn
    before_info = engine.analyse(board, limit)
    best_cp, _ = score_for_color(before_info, color)

    after_board = board.copy(stack=False)
    after_board.push(move)
    terminal = terminal_score(after_board, color)
    if terminal:
        after_cp, _ = terminal
    else:
        after_info = engine.analyse(after_board, limit)
        after_cp, _ = score_for_color(after_info, color)

    loss = max(0, best_cp - after_cp)
    if loss <= accept_cp:
        if loss == 0:
            return True, "best play."
        return True, f"strong - only {loss} cp from best."
    return False, f"loses {loss_phrase(loss)} versus the best move."


def parse_move(board: chess.Board, raw: str) -> Optional[chess.Move]:
    try:
        return board.parse_san(raw)
    except ValueError:
        pass
    try:
        move = chess.Move.from_uci(raw.lower())
    except ValueError:
        return None
    return move if move in board.legal_moves else None


def safe_san(board: chess.Board, move: chess.Move) -> str:
    try:
        return board.san(move)
    except (ValueError, AssertionError):
        return move.uci()


def hint_for(board: chess.Board, best_uci: str) -> str:
    if not best_uci:
        return "  No hint available for this puzzle."
    try:
        move = chess.Move.from_uci(best_uci)
    except ValueError:
        return "  No hint available for this puzzle."
    from_sq = chess.square_name(move.from_square)
    piece = board.piece_at(move.from_square)
    name = chess.piece_name(piece.piece_type).title() if piece else "piece"
    return f"  Hint: move your {name} on {from_sq}."


def render_board(board: chess.Board, orientation: chess.Color) -> str:
    ranks = range(7, -1, -1) if orientation == chess.WHITE else range(8)
    files = range(8) if orientation == chess.WHITE else range(7, -1, -1)
    lines = []
    for rank in ranks:
        row = [str(rank + 1)]
        for file in files:
            piece = board.piece_at(chess.square(file, rank))
            row.append(piece.symbol() if piece else ".")
        lines.append(" ".join(row))
    file_letters = "abcdefgh" if orientation == chess.WHITE else "hgfedcba"
    lines.append("  " + " ".join(file_letters))
    return "\n".join(lines)


def latest_puzzles_csv(root: Path = Path("analysis")) -> Optional[Path]:
    candidates = sorted(
        (
            path
            for candidate_root in analysis_roots(root)
            for path in candidate_root.glob("*/puzzles.csv")
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def analysis_roots(root: Path) -> List[Path]:
    expanded = root.expanduser()
    if expanded.is_absolute():
        return [expanded] if expanded.exists() else []

    roots = [Path.cwd() / expanded]
    script_root = SCRIPT_DIR / expanded
    if script_root not in roots:
        roots.append(script_root)
    return [candidate for candidate in roots if candidate.exists()]


def load_puzzle_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("fen") or "").strip()]


if __name__ == "__main__":
    raise SystemExit(main())
