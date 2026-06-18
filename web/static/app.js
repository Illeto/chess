"use strict";

const $ = (sel) => document.querySelector(sel);

async function loadEngine() {
  const el = $("#engine-status");
  try {
    const e = await (await fetch("/api/engine")).json();
    if (e.ready) { el.textContent = "Stockfish ready"; el.className = "engine ok"; }
    else { el.textContent = "no engine — run install-engine"; el.className = "engine bad"; }
  } catch { el.textContent = "engine status unknown"; }
}

async function loadRuns() {
  const box = $("#runs");
  try {
    const { runs } = await (await fetch("/api/runs")).json();
    if (!runs.length) { box.innerHTML = '<p class="muted">No runs yet. Start an analysis above.</p>'; return; }
    box.innerHTML = "";
    for (const r of runs) {
      const div = document.createElement("div");
      div.className = "run";
      div.innerHTML =
        `<div class="meta"><b>${esc(r.username)}</b> <span class="muted">${esc(r.stamp)}</span>` +
        `<div class="counts">${r.blunder} blunders · ${r.mistake} mistakes · ${r.inaccuracy} inaccuracies · ${r.puzzles} puzzles</div></div>` +
        `<div class="links">` +
        `<a class="btn primary" href="/run/${encodeURIComponent(r.id)}/profile">Profile</a>` +
        `<a class="btn" href="/run/${encodeURIComponent(r.id)}/review">Review</a>` +
        `<a class="btn" href="/run/${encodeURIComponent(r.id)}/solve">Solve</a></div>`;
      box.appendChild(div);
    }
  } catch { box.innerHTML = '<p class="error">Could not load runs.</p>'; }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function setPhase(job) {
  const phases = { fetching: "Fetching games…", analyzing: "Analyzing games", writing: "Writing report", done: "Done", queued: "Queued" };
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
