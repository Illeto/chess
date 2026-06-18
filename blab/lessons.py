"""Assemble a lesson for a blunder category: a concept explanation + a drill deck.

In this milestone the concept text is a curated template per category (the AI writer
in a later milestone can replace ``concept`` with a tailored version). The drill deck
is the indices of the user's own puzzles (from puzzles.csv) classified into that
category, which the GUI solver drills via the existing per-index endpoints.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from blab import puzzledb
from blab.classify import CATEGORY_LABELS

# Curated, beginner-facing concept per category: what it is, why it happens, the fix.
CATEGORY_CONCEPTS = {
    "hung_piece": {
        "what": "You left a piece where your opponent could win it — undefended, or attacked by something cheaper.",
        "why": "You focused on your own plan and didn't check whether your move left a piece unguarded or attacked.",
        "fix": "Before you move, scan every one of your opponent's captures. Ask: after my move, is each of my pieces defended or out of reach?",
    },
    "allowed_fork": {
        "what": "Your move let the opponent hit two pieces at once (often a knight or queen), so you lose one.",
        "why": "Undefended pieces, or your king and queen sitting a knight's-jump apart, invite forks.",
        "fix": "Check your opponent's checks and knight jumps. Keep valuable pieces defended and off the same fork squares.",
    },
    "allowed_pin_skewer": {
        "what": "Your move let the opponent pin or skewer a piece along a line and win material.",
        "why": "Lining up valuable pieces (especially with your king) on the same rank, file, or diagonal as an enemy rook, bishop, or queen.",
        "fix": "Avoid putting your king and queen/rook on an open line with an enemy long-range piece. Defend or challenge a pinned piece quickly.",
    },
    "allowed_discovered": {
        "what": "Your move allowed a discovered attack — the opponent moved one piece to unveil an attack from another.",
        "why": "An enemy piece was lined up behind one of its own, ready to spring once it stepped aside.",
        "fix": "Watch for enemy pieces stacked on a line aimed at your king or queen; a discovery is coming when the front piece can move with tempo.",
    },
    "walked_into_mate": {
        "what": "Your move allowed a forced checkmate.",
        "why": "King safety slipped — open lines to your king, a weak back rank, or too few defenders.",
        "fix": "When your king looks airy, count attackers vs defenders around it. Make luft to avoid back-rank mates, and meet checks with a defended block.",
    },
    "trade_counting_error": {
        "what": "You started a capture sequence that loses material — you gave back more than you won.",
        "why": "Miscounting the order and values in an exchange, especially with several pieces aimed at one square.",
        "fix": "Before capturing, count the whole sequence with the lowest-value attacker first. Only go in if you come out even or ahead.",
    },
    "missed_free_capture": {
        "what": "Your opponent left a piece hanging and you didn't take it.",
        "why": "You were following your own plan and missed the free material on offer.",
        "fix": "Every move, scan the opponent's pieces for anything undefended or attacked by something cheaper — then take it (unless it's a trap).",
    },
    "missed_tactic": {
        "what": "A tactic was available — a fork, a winning capture, even mate — and you played something else.",
        "why": "Forcing moves (checks, captures, threats) weren't on your radar.",
        "fix": "Look at all your checks and captures first. Most tactics begin with a forcing move you'd otherwise skip past.",
    },
    "positional_other": {
        "what": "This move lost ground without a clean one-move tactic — a slower positional slip.",
        "why": "It's about plans more than blunders: piece activity, pawn structure, and king safety.",
        "fix": "Develop toward the center, keep pawns flexible, and ask 'what is my worst piece, and how do I improve it?'",
    },
}


def build_lesson(
    category: str,
    puzzle_rows: List[dict],
    db_path: Optional[Path] = None,
    target: int = 8,
) -> dict:
    """Concept + a drill deck for a category.

    Drills are descriptors ``{"source": "own"|"db", "ref": ...}``: the user's own
    puzzles first (``ref`` is the puzzles.csv index), then theme-matched Lichess
    puzzles (``ref`` is a puzzle id) to top the deck up to ``target`` when the user
    has too few of their own. DB top-up is silently skipped if the DB isn't built.
    """
    concept = CATEGORY_CONCEPTS.get(category, CATEGORY_CONCEPTS["positional_other"])
    own = [
        i
        for i, row in enumerate(puzzle_rows)
        if (row.get("category") or "positional_other") == category
    ]
    drills: List[dict] = [{"source": "own", "ref": i} for i in own]

    db_rows: List[dict] = []
    if len(own) < target:
        themes = puzzledb.CATEGORY_THEMES.get(category, [])
        db_rows = puzzledb.query(themes, limit=target - len(own), db_path=db_path)
        drills += [
            {"source": "db", "ref": r["puzzle_id"], "theme": r["themes"], "rating": r["rating"]}
            for r in db_rows
        ]

    return {
        "category": category,
        "label": CATEGORY_LABELS.get(category, category),
        "concept": concept,
        "drills": drills,
        "own_count": len(own),
        "db_count": len(db_rows),
        "count": len(drills),
    }
