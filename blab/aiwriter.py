"""Plain-language coaching notes for a flagged move.

Research shows LLMs are unreliable at chess from a FEN, so the model never analyzes
the position: Stockfish + the classifier already produced the verdict, and this module
only *verbalizes* those validated facts. The prompt hard-constrains the model to the
supplied facts. Provider-pluggable (Anthropic default, local Ollama, or a deterministic
template fallback), and every result is cached to disk so each note costs at most once.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from blab.lessons import CATEGORY_CONCEPTS
from blab.classify import CATEGORY_LABELS

DEFAULT_MODEL = "claude-haiku-4-5"
OLLAMA_MODEL = "qwen3:8b"
CACHE_DIR = Path.home() / ".blunder_lab" / "ai_cache"

SYSTEM = (
    "You are a warm, encouraging chess coach writing for a beginner (~500 Elo). "
    "You are given FACTS about a single move that a chess engine already analysed. "
    "Write 2-3 short, plain-English sentences that explain the mistake and the better "
    "idea so the student understands the pattern. CRITICAL RULES: use ONLY the facts "
    "provided; never invent or mention a move, square, threat, piece, or evaluation "
    "that is not in the facts; do not analyse the position yourself; avoid jargon that "
    "the facts do not use. Be concrete and kind."
)


def provider_name(provider: Optional[str] = None) -> str:
    return provider or os.environ.get("BLAB_AI_PROVIDER") or "anthropic"


def available(provider: Optional[str] = None) -> bool:
    """Whether the configured provider can currently produce AI notes."""
    name = provider_name(provider)
    if name == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if name == "ollama":
        return True  # assume a local server; calls fail gracefully to template
    return False


def coach(facts: dict, provider: Optional[str] = None) -> Tuple[str, str]:
    """Return (text, source) where source is 'ai' or 'template'. Always succeeds."""
    text = explain(facts, provider=provider)
    if text:
        return text, "ai"
    return template_note(facts), "template"


def explain(facts: dict, provider: Optional[str] = None, model: Optional[str] = None) -> Optional[str]:
    """Grounded AI note, or None if the provider is unavailable or errors."""
    name = provider_name(provider)
    model = model or (OLLAMA_MODEL if name == "ollama" else DEFAULT_MODEL)
    cache_key = _cache_key(name, model, facts)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    if not available(name):
        return None
    prompt = _facts_to_prompt(facts)
    try:
        if name == "anthropic":
            text = _anthropic(prompt, model)
        elif name == "ollama":
            text = _ollama(prompt, model)
        else:
            text = None
    except Exception:
        text = None
    if text:
        _cache_put(cache_key, text)
    return text


# ---------- providers ----------

def _anthropic(prompt: str, model: str) -> Optional[str]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=300,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if getattr(response, "stop_reason", None) == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


def _ollama(prompt: str, model: str) -> Optional[str]:
    body = json.dumps(
        {"model": model, "system": SYSTEM, "prompt": prompt, "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("response") or "").strip() or None


# ---------- template fallback ----------

def template_note(facts: dict) -> str:
    category = facts.get("category") or "positional_other"
    concept = CATEGORY_CONCEPTS.get(category, CATEGORY_CONCEPTS["positional_other"])
    your_move = facts.get("your_move_san") or "your move"
    best_move = facts.get("best_move_san") or "the engine's move"
    label = CATEGORY_LABELS.get(category, category).lower()
    return (
        f"You played {your_move} — {label}. {concept['fix']} "
        f"Here the engine preferred {best_move}."
    )


# ---------- helpers ----------

_FACT_FIELDS = [
    ("Mistake type", "category_label"),
    ("Your move", "your_move_san"),
    ("Engine's best move", "best_move_san"),
    ("Engine's line", "pv_san"),
    ("Tactics involved", "motifs"),
    ("Evaluation before your move", "eval_before"),
    ("Evaluation after your move", "eval_after"),
    ("You were playing", "user_color"),
]


def _facts_to_prompt(facts: dict) -> str:
    facts = dict(facts)
    facts.setdefault(
        "category_label", CATEGORY_LABELS.get(facts.get("category", ""), facts.get("category", ""))
    )
    lines = ["FACTS:"]
    for label, key in _FACT_FIELDS:
        value = facts.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    lines.append("")
    lines.append("Write the coaching note now, using only these facts.")
    return "\n".join(lines)


def _cache_key(provider: str, model: str, facts: dict) -> str:
    payload = json.dumps([provider, model, facts], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cache_get(key: str) -> Optional[str]:
    path = CACHE_DIR / f"{key}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _cache_put(key: str, text: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.txt").write_text(text, encoding="utf-8")
