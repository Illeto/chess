"use strict";

const RUN_ID = document.body.dataset.runId;
const $ = (s) => document.querySelector(s);
const boardEl = $("#board");

const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];

let count = 0;
let index = 0;
let solved = 0;
let attempted = 0;

let fen = "";
let side = "white";
let legal = [];
const themes = {};

// interaction state
let selected = null;   // square highlighted for click-to-move / drag source
let dragFrom = null;   // square the pointer pressed on (a movable piece)
let moved = false;     // pointer moved far enough to count as a drag
let ghost = null;
let answered = false;
let submitting = false;
let lastMove = null;   // [from, to] to highlight after a move

// ---------- data ----------

async function init() {
  const data = await api(`/api/runs/${enc(RUN_ID)}/puzzles`);
  count = data.count;
  for (const it of data.items) themes[it.index] = it.theme;
  if (!count) { $("#title").textContent = "No puzzles in this run"; boardEl.innerHTML = ""; return; }
  load(0);
}

async function load(i) {
  index = i;
  answered = false;
  submitting = false;
  selected = dragFrom = null;
  moved = false;
  lastMove = null;
  removeGhost();
  $("#result").classList.add("hidden");
  $("#next").classList.add("hidden");
  $("#hint").disabled = false;
  $("#skip").disabled = false;
  $("#promo").classList.add("hidden");
  const p = await api(`/api/runs/${enc(RUN_ID)}/puzzles/${index}/legal`);
  fen = p.fen; side = p.side; legal = p.legal;
  $("#title").textContent = `Puzzle ${index + 1} of ${count}`;
  $("#turn").textContent = `You are ${side === "white" ? "White" : "Black"} to move`;
  $("#theme").textContent = themes[index] || "—";
  $("#counter").textContent = `${index + 1} / ${count}`;
  render();
}

// ---------- rendering ----------

function fenToMap(f) {
  const map = {};
  const rows = f.split(" ")[0].split("/");
  for (let i = 0; i < 8; i++) {
    const rank = 8 - i;
    let file = 0;
    for (const ch of rows[i]) {
      if (/\d/.test(ch)) file += parseInt(ch, 10);
      else { map[FILES[file] + rank] = ch; file++; }
    }
  }
  return map;
}

function render() {
  const map = fenToMap(fen);
  const ranks = side === "white" ? [8, 7, 6, 5, 4, 3, 2, 1] : [1, 2, 3, 4, 5, 6, 7, 8];
  const files = side === "white" ? FILES : [...FILES].reverse();
  boardEl.innerHTML = "";
  for (const rank of ranks) {
    for (const file of files) {
      const sq = file + rank;
      const cell = document.createElement("div");
      const dark = (FILES.indexOf(file) + rank) % 2 === 1;
      cell.className = "sq " + (dark ? "dark" : "light");
      cell.dataset.square = sq;
      if (!answered && movesFrom(sq).length) cell.classList.add("has-move");
      const piece = map[sq];
      if (piece) {
        const img = document.createElement("img");
        img.className = "piece-img";
        img.draggable = false;
        img.src = `/api/piece/${piece}`;
        cell.appendChild(img);
      }
      boardEl.appendChild(cell);
    }
  }
  paintHighlights();
}

function paintHighlights() {
  const map = fenToMap(fen);
  for (const cell of boardEl.querySelectorAll(".sq")) {
    cell.classList.remove("sel", "target", "occupied", "last");
    const sq = cell.dataset.square;
    if (lastMove && (sq === lastMove[0] || sq === lastMove[1])) cell.classList.add("last");
    if (sq === selected) cell.classList.add("sel");
  }
  if (selected) {
    for (const u of legal.filter((u) => u.slice(0, 2) === selected)) {
      const t = cellFor(u.slice(2, 4));
      if (t) { t.classList.add("target"); if (map[u.slice(2, 4)]) t.classList.add("occupied"); }
    }
  }
}

const cellFor = (sq) => boardEl.querySelector(`.sq[data-square="${sq}"]`);
const movesFrom = (sq) => legal.filter((u) => u.slice(0, 2) === sq);
const between = (from, to) => legal.filter((u) => u.slice(0, 2) === from && u.slice(2, 4) === to);

// ---------- pointer drag + click ----------

let startX = 0, startY = 0;

boardEl.addEventListener("pointerdown", (e) => {
  if (answered || submitting) return;
  const cell = e.target.closest(".sq");
  if (!cell) return;
  const sq = cell.dataset.square;
  if (selected && sq !== selected && between(selected, sq).length) { doMove(selected, sq); return; }
  if (movesFrom(sq).length) {
    selected = sq; dragFrom = sq; moved = false;
    startX = e.clientX; startY = e.clientY;
    paintHighlights();
    try { boardEl.setPointerCapture(e.pointerId); } catch {}
  } else {
    selected = null; paintHighlights();
  }
});

boardEl.addEventListener("pointermove", (e) => {
  if (!dragFrom) return;
  if (!moved && Math.hypot(e.clientX - startX, e.clientY - startY) > 4) { moved = true; makeGhost(); }
  if (moved) positionGhost(e.clientX, e.clientY);
});

boardEl.addEventListener("pointerup", (e) => {
  if (!dragFrom) return;
  const from = dragFrom; dragFrom = null;
  const wasMoved = moved; moved = false;
  removeGhost();
  if (!wasMoved) { selected = from; paintHighlights(); return; }  // a click, keep selection
  let drop = null;
  const el = document.elementFromPoint(e.clientX, e.clientY);
  if (el) { const c = el.closest(".sq"); if (c) drop = c.dataset.square; }
  if (drop && drop !== from && between(from, drop).length) doMove(from, drop);
  else { selected = null; paintHighlights(); }
});

boardEl.addEventListener("pointercancel", () => { dragFrom = null; moved = false; removeGhost(); });

function makeGhost() {
  const sym = fenToMap(fen)[dragFrom];
  if (!sym) return;
  const rect = cellFor(dragFrom).getBoundingClientRect();
  ghost = document.createElement("div");
  ghost.className = "ghost";
  ghost.style.width = rect.width + "px";
  ghost.style.height = rect.height + "px";
  const img = document.createElement("img");
  img.src = `/api/piece/${sym}`;
  ghost.appendChild(img);
  document.body.appendChild(ghost);
  const src = cellFor(dragFrom).querySelector("img");
  if (src) src.classList.add("drag-src");
}

function positionGhost(x, y) {
  if (!ghost) return;
  ghost.style.left = x - ghost.offsetWidth / 2 + "px";
  ghost.style.top = y - ghost.offsetHeight / 2 + "px";
}

function removeGhost() {
  if (ghost) { ghost.remove(); ghost = null; }
  boardEl.querySelectorAll(".drag-src").forEach((el) => el.classList.remove("drag-src"));
}

// ---------- moving / grading ----------

function doMove(from, to) {
  const candidates = between(from, to);
  if (candidates.length === 0) { selected = null; paintHighlights(); return; }
  if (candidates.length === 1) submit(candidates[0], from, to);
  else choosePromotion(candidates, from, to);
}

function choosePromotion(candidates, from, to) {
  const promo = $("#promo");
  promo.innerHTML = "";
  promo.classList.remove("hidden");
  for (const uci of candidates) {
    const letter = uci[4] || "q";
    const sym = side === "white" ? letter.toUpperCase() : letter;
    const btn = document.createElement("button");
    const img = document.createElement("img");
    img.src = `/api/piece/${sym}`;
    btn.appendChild(img);
    btn.addEventListener("click", () => { promo.classList.add("hidden"); submit(uci, from, to); });
    promo.appendChild(btn);
  }
}

async function submit(uci, from, to) {
  if (submitting) return;
  submitting = true;
  selected = null;
  $("#hint").disabled = true;
  $("#skip").disabled = true;

  let g;
  try {
    g = await api(`/api/runs/${enc(RUN_ID)}/puzzles/${index}/grade`, { move: uci });
  } catch (err) {
    submitting = false;
    selected = from;
    paintHighlights();
    $("#hint").disabled = false;
    $("#skip").disabled = false;
    const box = $("#result");
    box.className = "result no";
    box.textContent = "Could not grade move: " + err.message;
    box.classList.remove("hidden");
    return;
  }

  answered = true;
  submitting = false;
  lastMove = [from, to];
  render();
  attempted += 1;
  if (g.correct) solved += 1;
  $("#solved").textContent = solved;
  $("#attempted").textContent = attempted;
  const box = $("#result");
  box.className = "result " + (g.correct ? "ok" : "no");
  box.innerHTML = `<b>${g.correct ? "✓" : "✗"} ${esc(g.your_san)}</b> — ${esc(g.detail)}` +
    `<br>Best: ${esc(g.best_san)} <span class="muted">(${esc(g.pv_san)})</span>`;
  box.classList.remove("hidden");
  if (index < count - 1) $("#next").classList.remove("hidden");
  else $("#done").classList.remove("hidden");
}

async function hint() {
  const h = await api(`/api/runs/${enc(RUN_ID)}/puzzles/${index}/hint`);
  if (!h.square) return;
  selected = h.square;
  paintHighlights();
  const box = $("#result");
  box.className = "result";
  box.textContent = `Hint: move your ${h.piece} on ${h.square}.`;
  box.classList.remove("hidden");
}

// ---------- helpers ----------

const enc = encodeURIComponent;
async function api(url, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined;
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("#hint").addEventListener("click", hint);
$("#skip").addEventListener("click", () => { if (index < count - 1) load(index + 1); else $("#done").classList.remove("hidden"); });
$("#next").addEventListener("click", () => load(index + 1));

init();
