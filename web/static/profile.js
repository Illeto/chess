"use strict";

const RUN_ID = document.body.dataset.runId;

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
const pawns = (cp) => (cp >= 10000 ? "mate-level" : (cp / 100).toFixed(1));

async function load() {
  const box = document.getElementById("profile");
  let data;
  try {
    data = await (await fetch(`/api/runs/${encodeURIComponent(RUN_ID)}/profile`)).json();
  } catch {
    box.innerHTML = '<p class="error">Could not load the error profile.</p>';
    return;
  }
  const profile = data.profile || [];
  if (!profile.length) {
    box.innerHTML = '<p class="muted">No findings in this run.</p>';
    return;
  }
  const max = profile[0].total_loss_cp || 1;
  box.innerHTML = "";
  profile.forEach((g, i) => {
    const width = Math.max(3, Math.round((g.total_loss_cp / max) * 100));
    const motifs = (g.motifs || []).slice(0, 4).map((m) => `${esc(m[0])} ×${m[1]}`).join(", ") || "—";
    const phase = (g.phases && g.phases[0]) ? esc(g.phases[0][0]) : "—";
    const card = document.createElement("div");
    card.className = "profile-card";
    card.innerHTML =
      `<div class="rank">${i + 1}</div>` +
      `<div class="body">` +
      `<div class="head"><b>${esc(g.label)}</b>` +
      `<span class="muted">${g.count} error(s) · ${pawns(g.total_loss_cp)} pawns · ${Math.round(g.share * 100)}%</span></div>` +
      `<div class="bar"><div class="bar-fill" style="width:${width}%"></div></div>` +
      `<div class="sub muted">Motifs: ${motifs} · mostly ${phase}</div>` +
      `</div>` +
      `<a class="btn primary" href="/run/${encodeURIComponent(RUN_ID)}/solve?category=${encodeURIComponent(g.category)}">Drill</a>`;
    box.appendChild(card);
  });
}

load();
