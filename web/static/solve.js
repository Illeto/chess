"use strict";

import { Chessboard, COLOR, INPUT_EVENT_TYPE, BORDER_TYPE, FEN } from "/static/vendor/cm-chessboard/src/Chessboard.js";
import { Markers, MARKER_TYPE } from "/static/vendor/cm-chessboard/src/extensions/markers/Markers.js";
import { PromotionDialog } from "/static/vendor/cm-chessboard/src/extensions/promotion-dialog/PromotionDialog.js";

const RUN_ID = document.body.dataset.runId;
const $ = (s) => document.querySelector(s);
const enc = encodeURIComponent;
const ASSETS = "/static/vendor/cm-chessboard/assets/";
const CATEGORY = new URLSearchParams(location.search).get("category");

let count = 0, index = 0, solved = 0, attempted = 0;
let side = "white", legal = [], order = [], submitting = false, currentFen = FEN.start;
let replayToken = 0;
const themes = {};
const cur = () => order[index];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function puzUrl(d, suffix) {
  return d.source === "db"
    ? `/api/db/puzzles/${enc(d.ref)}/${suffix}`
    : `/api/runs/${enc(RUN_ID)}/puzzles/${d.ref}/${suffix}`;
}
const cmColor = () => (side === "white" ? COLOR.white : COLOR.black);

const board = new Chessboard($("#board"), {
  position: FEN.empty,
  assetsUrl: ASSETS,
  style: { pieces: { file: "pieces/standard.svg" }, showCoordinates: true, borderType: BORDER_TYPE.frame },
  extensions: [{ class: Markers, props: {} }, { class: PromotionDialog }],
});

// ---------- data / flow ----------

async function init() {
  const data = await api(`/api/runs/${enc(RUN_ID)}/puzzles`);
  for (const it of data.items) themes[it.index] = it.theme;
  order = data.items.map((it) => ({ source: "own", ref: it.index }));
  if (CATEGORY) {
    const lesson = await api(`/api/runs/${enc(RUN_ID)}/lessons/${enc(CATEGORY)}`);
    order = lesson.drills || [];
    renderConcept(lesson);
  }
  count = order.length;
  if (!count) {
    $("#title").textContent = CATEGORY ? "No drills from your own games here yet" : "No puzzles in this run";
    return;
  }
  load(0);
}

function renderConcept(lesson) {
  const el = $("#concept");
  if (!el) return;
  const c = lesson.concept || {};
  el.innerHTML =
    `<h2>${esc(lesson.label)}</h2>` +
    `<p><b>What happened:</b> ${esc(c.what || "")}</p>` +
    `<p><b>Why:</b> ${esc(c.why || "")}</p>` +
    `<p><b>The fix:</b> ${esc(c.fix || "")}</p>`;
  el.classList.remove("hidden");
  document.title = lesson.label + " · Lesson";
}

async function load(i) {
  index = i;
  submitting = false;
  replayToken += 1;
  $("#result").classList.add("hidden");
  $("#next").classList.add("hidden");
  $("#done").classList.add("hidden");
  $("#hint").disabled = false;
  $("#skip").disabled = false;
  const d = cur();
  const p = await api(puzUrl(d, "legal"));
  side = p.side;
  legal = p.legal;
  currentFen = p.fen;
  board.removeMarkers();
  await board.setOrientation(cmColor());
  await board.setPosition(p.fen, false);
  board.enableMoveInput(inputHandler, cmColor());
  $("#title").textContent = `${CATEGORY ? "Drill" : "Puzzle"} ${index + 1} of ${count}`;
  $("#turn").textContent = `You are ${side === "white" ? "White" : "Black"} to move`;
  const themeText = d.source === "db"
    ? (p.theme || "Lichess puzzle") + (p.rating ? ` · Lichess ${p.rating}` : "")
    : themes[d.ref];
  $("#theme").textContent = themeText || "—";
  $("#counter").textContent = `${index + 1} / ${count}`;
}

const movesFrom = (sq) => legal.filter((u) => u.slice(0, 2) === sq);

// ---------- move input (drag + click via cm-chessboard) ----------

function inputHandler(event) {
  if (event.type === INPUT_EVENT_TYPE.moveInputStarted) {
    const targets = movesFrom(event.square).map((u) => u.slice(2, 4));
    targets.forEach((sq) => board.addMarker(MARKER_TYPE.dot, sq));
    return targets.length > 0;
  }
  if (event.type === INPUT_EVENT_TYPE.moveInputCanceled) {
    board.removeMarkers(MARKER_TYPE.dot);
    return;
  }
  if (event.type === INPUT_EVENT_TYPE.validateMoveInput) {
    board.removeMarkers(MARKER_TYPE.dot);
    const base = event.squareFrom + event.squareTo;
    const candidates = legal.filter((u) => u.slice(0, 4) === base);
    if (!candidates.length) return false;
    if (candidates.length > 1) {
      board.showPromotionDialog(event.squareTo, cmColor(), (res) => {
        if (res && res.piece) submit(base + res.piece.charAt(1));
        else board.setPosition(currentFen, false);
      });
      return true;
    }
    submit(candidates[0]);
    return true;
  }
  return true;
}

// ---------- grading ----------

async function submit(uci) {
  if (submitting) return;
  submitting = true;
  board.disableMoveInput();
  $("#hint").disabled = true;
  $("#skip").disabled = true;

  let g;
  try {
    g = await api(puzUrl(cur(), "grade"), { move: uci });
  } catch (err) {
    submitting = false;
    board.enableMoveInput(inputHandler, cmColor());
    $("#hint").disabled = false;
    $("#skip").disabled = false;
    showResult("no", "Could not grade move: " + esc(err.message));
    return;
  }

  submitting = false;
  attempted += 1;
  if (g.correct) solved += 1;
  $("#solved").textContent = solved;
  $("#attempted").textContent = attempted;
  const box = $("#result");
  box.className = "result " + (g.correct ? "ok" : "no");
  box.innerHTML =
    `<div><b>${g.correct ? "✓" : "✗"} ${humanMoveHtml(g.your_san)}</b> — ${esc(g.detail)}</div>` +
    `<div class="best-line">Best: ${humanMoveHtml(g.best_san)} ` +
    `<button id="replay" class="btn small">▶ Show the line</button></div>` +
    `<div class="muted pv">${esc(g.pv_san)}</div>`;
  box.classList.remove("hidden");
  const replayBtn = document.getElementById("replay");
  if (replayBtn) replayBtn.addEventListener("click", replayLine);
  if (index < count - 1) $("#next").classList.remove("hidden");
  else $("#done").classList.remove("hidden");
}

function showResult(cls, html) {
  const box = $("#result");
  box.className = "result " + cls;
  box.innerHTML = html;
  box.classList.remove("hidden");
}

async function hint() {
  const h = await api(puzUrl(cur(), "hint"));
  if (!h.square) return;
  board.removeMarkers(MARKER_TYPE.frame);
  board.addMarker(MARKER_TYPE.frame, h.square);
  showResult("", `Hint: move your ${esc(h.piece)} on ${esc(h.square)}.`);
}

// ---------- readable move text + line replay ----------

const PIECE_NAME = { N: "Knight", B: "Bishop", R: "Rook", Q: "Queen", K: "King", P: "Pawn" };

function humanizeSan(san) {
  let s = String(san).replace(/[+#]$/, "");
  const suffix = san.endsWith("#") ? ", checkmate" : san.endsWith("+") ? ", check" : "";
  if (s === "O-O") return "Castles kingside" + suffix;
  if (s === "O-O-O") return "Castles queenside" + suffix;
  let promo = "";
  const pm = s.match(/=([QRBN])$/);
  if (pm) { promo = ", promotes to " + PIECE_NAME[pm[1]]; s = s.replace(/=([QRBN])$/, ""); }
  const dest = s.slice(-2);
  const piece = "NBRQK".includes(s[0]) ? PIECE_NAME[s[0]] : "Pawn";
  const verb = s.includes("x") ? "takes" : "to";
  return `${piece} ${verb} ${dest}${promo}${suffix}`;
}

function moveIconSym(san) {
  const s = String(san).replace(/[+#]$/, "");
  const letter = s.startsWith("O-O") ? "K" : "NBRQK".includes(s[0]) ? s[0] : "P";
  return side === "white" ? letter : letter.toLowerCase();
}

function humanMoveHtml(san) {
  return `<img class="ic" src="/api/piece/${moveIconSym(san)}" alt=""> ${esc(humanizeSan(san))}`;
}

async function replayLine() {
  const token = ++replayToken;
  const btn = document.getElementById("replay");
  if (btn) btn.disabled = true;
  let data;
  try {
    data = await api(puzUrl(cur(), "line"));
  } catch {
    return;
  }
  const steps = data.steps || [];
  if (!steps.length) return;
  board.disableMoveInput();
  board.removeMarkers();
  await board.setPosition(data.start_fen, true);
  if (token !== replayToken) return;
  for (let k = 0; k < steps.length; k++) {
    await sleep(850);
    if (token !== replayToken) return;
    await board.setPosition(steps[k].fen, true);
    if (token !== replayToken) return;
    $("#turn").textContent = `${k + 1}. ${humanizeSan(steps[k].san)}`;
  }
}

// ---------- helpers ----------

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
