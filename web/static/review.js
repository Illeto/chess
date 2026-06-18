"use strict";

const RUN_ID = document.body.dataset.runId;
let index = 0;
let count = 0;

const $ = (s) => document.querySelector(s);

async function init() {
  const data = await (await fetch(`/api/runs/${encodeURIComponent(RUN_ID)}/findings`)).json();
  count = data.count;
  if (!count) {
    $("#board").innerHTML = '<p class="muted">No findings in this run.</p>';
    $("#title").textContent = "Nothing flagged";
    return;
  }
  show(0);
}

async function show(i) {
  index = Math.max(0, Math.min(count - 1, i));
  const f = await (await fetch(`/api/runs/${encodeURIComponent(RUN_ID)}/findings/${index}`)).json();
  $("#board").innerHTML = f.svg || "";
  const dots = f.user_color === "White" ? "." : "...";
  $("#title").textContent = `${cap(f.kind)} on ${f.move_number}${dots} ${f.your_move_san}`;
  const noteEl = $("#note");
  noteEl.textContent = f.note ? (f.note_source === "ai" ? "🧠 " : "") + f.note : "";
  $("#your-move").textContent = f.your_move_san || "–";
  $("#best-move").textContent = f.best_move_san || "–";
  $("#eval").textContent = `${f.eval_before} → ${f.eval_after}`;
  $("#loss").textContent = lossText(f.loss_cp);
  $("#pv").textContent = f.pv_san || f.best_move_san || "–";
  $("#theme").textContent = f.theme || "–";
  $("#counter").textContent = `${index + 1} / ${count}`;
  const link = $("#game-link");
  if (f.url) { link.href = f.url; link.classList.remove("hidden"); } else { link.classList.add("hidden"); }
  $("#prev").disabled = index === 0;
  $("#next").disabled = index === count - 1;
}

function lossText(cp) {
  const n = parseInt(cp, 10);
  if (!isFinite(n)) return "–";
  if (n >= 10000) return "mate swing";
  return (n / 100).toFixed(2) + " pawns";
}
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

$("#prev").addEventListener("click", () => show(index - 1));
$("#next").addEventListener("click", () => show(index + 1));
document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") show(index - 1);
  if (e.key === "ArrowRight") show(index + 1);
});

init();
