"""Aggregate classified findings into an impact-ranked error profile.

The point of the whole tool: group mistakes by *cause category*, and rank the groups
by total centipawns lost so the user fixes the biggest leak first. Works on either
``MoveFinding`` objects or CSV dict rows (anything exposing category/motifs/phase/loss_cp).
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, List

from blab.classify import CATEGORY_LABELS

# Cap each finding's impact so a handful of forced mates (encoded as ~100000 cp) don't
# swamp the ranking. ~1000 cp ≈ "lost a decisive amount"; ranking then reflects how
# *often* a category hurts you, not just a few catastrophic swings.
IMPACT_CAP_CP = 1000


def _get(row, key: str):
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _split_motifs(value) -> List[str]:
    if not value:
        return []
    return [m.strip() for m in str(value).split(",") if m.strip()]


def build_error_profile(rows: Iterable) -> List[dict]:
    """Return category groups ranked by total centipawns lost (biggest leak first)."""
    groups: dict = {}
    total_loss = 0
    for row in rows:
        category = _get(row, "category") or "positional_other"
        loss = min(IMPACT_CAP_CP, _as_int(_get(row, "loss_cp")))
        total_loss += loss
        group = groups.setdefault(
            category,
            {
                "category": category,
                "label": CATEGORY_LABELS.get(category, category),
                "count": 0,
                "total_loss_cp": 0,
                "_motifs": Counter(),
                "_phases": Counter(),
            },
        )
        group["count"] += 1
        group["total_loss_cp"] += loss
        for motif in _split_motifs(_get(row, "motifs")):
            group["_motifs"][motif] += 1
        phase = _get(row, "phase")
        if phase:
            group["_phases"][phase] += 1

    profile: List[dict] = []
    for group in groups.values():
        count = group["count"]
        group["avg_loss_cp"] = round(group["total_loss_cp"] / count) if count else 0
        group["share"] = (group["total_loss_cp"] / total_loss) if total_loss else 0.0
        group["motifs"] = group.pop("_motifs").most_common()
        group["phases"] = group.pop("_phases").most_common()
        profile.append(group)

    profile.sort(key=lambda g: (g["total_loss_cp"], g["count"]), reverse=True)
    return profile


def _pawns(cp: int) -> str:
    if cp >= 10000:
        return "mate-level"
    return f"{cp / 100:.1f}"


def format_profile_lines(profile: List[dict]) -> List[str]:
    """Markdown lines for the report's Error Profile section."""
    if not profile:
        return []
    lines = [
        "## Error Profile",
        "",
        "Your mistakes by type, ranked by total centipawns lost — fix the top one first:",
        "",
    ]
    for rank, group in enumerate(profile, start=1):
        motifs = ", ".join(name for name, _ in group["motifs"][:3]) or "—"
        top_phase = group["phases"][0][0] if group["phases"] else "—"
        lines.append(
            f"{rank}. **{group['label']}** — {group['count']} error(s), "
            f"{_pawns(group['total_loss_cp'])} pawns lost "
            f"({group['share'] * 100:.0f}%). Motifs: {motifs}. Mostly {top_phase}."
        )
    lines.append("")
    return lines
