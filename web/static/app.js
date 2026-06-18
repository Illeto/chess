"use strict";

const $ = (sel) => document.querySelector(sel);
const enc = encodeURIComponent;

async function loadEngine() {
  const el = $("#engine-status");
  try {
    const e = await (await fetch("/api/engine")).json();
    if (e.ready) {
      el.textContent = "Stockfish ready";
      el.className = "engine ok";
    } else {
      el.textContent = "No engine: run install-engine";
      el.className = "engine bad";
    }
  } catch {
    el.textContent = "Engine status unknown";
  }
}

async function loadRuns() {
  const box = $("#runs");
  try {
    const { runs } = await (await fetch("/api/runs")).json();
    if (!runs.length) {
      box.innerHTML = '<p class="muted empty">No runs yet. Start an analysis above.</p>';
      renderEmptyFocus();
      return;
    }
    renderFocus(runs[0]);
    box.innerHTML = "";
    for (const r of runs) {
      const div = document.createElement("div");
      div.className = "run";
      div.innerHTML =
        `<div class="meta"><b>${esc(r.username)}</b> <span class="muted">${esc(r.stamp)}</span>` +
        `<div class="counts">${r.blunder} blunders · ${r.mistake} mistakes · ${r.inaccuracy} inaccuracies · ${r.puzzles} puzzles</div></div>` +
        `<div class="links">` +
        `<a class="btn primary" href="/run/${enc(r.id)}/profile">Profile</a>` +
        `<a class="btn" href="/run/${enc(r.id)}/review">Review</a>` +
        `<a class="btn" href="/run/${enc(r.id)}/solve">Solve</a></div>`;
      box.appendChild(div);
    }
  } catch {
    box.innerHTML = '<p class="error">Could not load runs.</p>';
  }
}

async function renderFocus(run) {
  $("#focus-title").textContent = `${run.username} latest study set`;
  $("#focus-copy").textContent = `${run.findings} findings and ${run.puzzles} puzzles from ${run.stamp}.`;
  $("#focus-actions").innerHTML =
    `<a class="btn primary" href="/run/${enc(run.id)}/profile">Open Profile</a>` +
    `<a class="btn" href="/run/${enc(run.id)}/solve">Start Solving</a>`;
  $("#focus-stats").innerHTML =
    stat("Blunders", run.blunder) +
    stat("Mistakes", run.mistake) +
    stat("Puzzles", run.puzzles);

  try {
    const data = await (await fetch(`/api/runs/${enc(run.id)}/profile`)).json();
    const top = (data.profile || [])[0];
    if (!top) return;
    $("#focus-title").textContent = compactLabel(top.label);
    $("#focus-copy").textContent =
      `${top.count} error(s), ${pawns(top.total_loss_cp)} pawns of capped impact, mostly ${top.phases?.[0]?.[0] || "mixed"}.`;
    $("#focus-actions").innerHTML =
      `<a class="btn primary" href="/run/${enc(run.id)}/solve?category=${enc(top.category)}">Drill Top Leak</a>` +
      `<a class="btn" href="/run/${enc(run.id)}/review">Review Examples</a>`;
    $("#focus-stats").innerHTML =
      stat("Share", `${Math.round(top.share * 100)}%`) +
      stat("Errors", top.count) +
      stat("Avg Loss", pawns(top.avg_loss_cp));
  } catch {
    // The latest run card is still useful without profile details.
  }
}

function renderEmptyFocus() {
  $("#focus-title").textContent = "No study set yet";
  $("#focus-copy").textContent = "Run your first analysis to build a profile and drill deck.";
  $("#focus-actions").innerHTML = "";
  $("#focus-stats").innerHTML = stat("Runs", 0) + stat("Findings", 0) + stat("Puzzles", 0);
}

function stat(label, value) {
  return `<div><b>${esc(value)}</b><span>${esc(label)}</span></div>`;
}

function pawns(cp) {
  const n = Number(cp) || 0;
  return n >= 10000 ? "mate-level" : (n / 100).toFixed(1);
}

function compactLabel(label) {
  return String(label).replace(" / ", "/");
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function setPhase(job) {
  const phases = { fetching: "Fetching games", analyzing: "Analyzing games", writing: "Writing report", done: "Done", queued: "Queued" };
  $("#job-phase").textContent = phases[job.phase] || job.phase;
  $("#job-label").textContent = job.label || "";
  const pct = job.total ? Math.round((job.done / job.total) * 100) : (job.phase === "fetching" ? 5 : 0);
  $("#job-bar").style.width = pct + "%";
}

async function pollJob(jobId) {
  const job = await (await fetch(`/api/jobs/${jobId}`)).json();
  setPhase(job);
  if (job.status === "succeeded") {
    $("#job-bar").style.width = "100%";
    await loadRuns();
    setTimeout(() => $("#job").classList.add("hidden"), 1500);
    return;
  }
  if (job.status === "failed") {
    const err = $("#job-error");
    err.textContent = "Error: " + (job.error || "analysis failed");
    err.classList.remove("hidden");
    return;
  }
  setTimeout(() => pollJob(jobId), 1000);
}

$("#analyze-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const body = Object.fromEntries(fd.entries());
  $("#job").classList.remove("hidden");
  $("#job-error").classList.add("hidden");
  setPhase({ phase: "queued", label: "", done: 0, total: 0 });
  const res = await fetch("/api/analyze", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    const err = $("#job-error");
    err.textContent = e.error || "Could not start analysis.";
    err.classList.remove("hidden");
    return;
  }
  const { job_id } = await res.json();
  pollJob(job_id);
});

loadEngine();
loadRuns();
