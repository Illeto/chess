"use strict";

const RUN_ID = document.body.dataset.runId;
const enc = encodeURIComponent;

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

const pawns = (cp) => (cp >= 10000 ? "mate-level" : (cp / 100).toFixed(1));

async function load() {
  const box = document.getElementById("profile");
  let data;
  try {
    data = await (await fetch(`/api/runs/${enc(RUN_ID)}/profile`)).json();
  } catch {
    box.innerHTML = '<p class="error">Could not load the error profile.</p>';
    return;
  }
  const profile = data.profile || [];
  if (!profile.length) {
    document.getElementById("profile-title").textContent = "No findings yet";
    document.getElementById("profile-copy").textContent = "This run has no classified mistakes.";
    box.innerHTML = '<p class="muted empty">No findings in this run.</p>';
    return;
  }
  renderSummary(profile[0]);
  renderCards(profile);
}

function renderSummary(top) {
  document.getElementById("profile-title").textContent = compactLabel(top.label);
  document.getElementById("profile-copy").textContent =
    `${top.count} error(s), ${pawns(top.total_loss_cp)} pawns of capped impact, mostly ${top.phases?.[0]?.[0] || "mixed"}.`;
  document.getElementById("profile-actions").innerHTML =
    `<a class="btn primary" href="/run/${enc(RUN_ID)}/solve?category=${enc(top.category)}">Drill This Pattern</a>` +
    `<a class="btn" href="/run/${enc(RUN_ID)}/review">Review Positions</a>`;
  document.getElementById("profile-stats").innerHTML =
    stat("Share", `${Math.round(top.share * 100)}%`) +
    stat("Errors", top.count) +
    stat("Avg Loss", pawns(top.avg_loss_cp));
}

function renderCards(profile) {
  const box = document.getElementById("profile");
  const max = profile[0].total_loss_cp || 1;
  box.innerHTML = "";
  profile.forEach((g, i) => {
    const width = Math.max(3, Math.round((g.total_loss_cp / max) * 100));
    const motifs = (g.motifs || []).slice(0, 4).map((m) => `<span class="pill">${esc(m[0])} ×${m[1]}</span>`).join("") || '<span class="pill">mixed</span>';
    const phase = (g.phases && g.phases[0]) ? esc(g.phases[0][0]) : "mixed";
    const card = document.createElement("article");
    card.className = "profile-card";
    card.innerHTML =
      `<div class="rank">${i + 1}</div>` +
      `<div class="body">` +
      `<div class="head"><b>${esc(g.label)}</b>` +
      `<span>${g.count} error(s) · ${pawns(g.total_loss_cp)} pawns · ${Math.round(g.share * 100)}%</span></div>` +
      `<div class="bar"><div class="bar-fill" style="width:${width}%"></div></div>` +
      `<div class="sub"><span>Mostly ${phase}</span><span class="motifs">${motifs}</span></div>` +
      `</div>` +
      `<a class="btn primary" href="/run/${enc(RUN_ID)}/solve?category=${enc(g.category)}">Drill</a>`;
    box.appendChild(card);
  });
}

function stat(label, value) {
  return `<div><b>${esc(value)}</b><span>${esc(label)}</span></div>`;
}

function compactLabel(label) {
  return String(label).replace(" / ", "/");
}

load();
