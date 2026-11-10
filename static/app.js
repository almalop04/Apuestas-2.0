const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v, d = 1) => (v * 100).toFixed(d) + " %";
const fmtDate = (iso) =>
  new Date(iso).toLocaleString("es-ES", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function form(str) {
  if (!str) return "";
  return `<span class="form">${[...str].map((c) => `<i class="${esc(c)}">${c === "W" ? "V" : c === "D" ? "E" : "D"}</i>`).join("")}</span>`;
}

const VERDICT = { mantener: "Mantener", reducir: "Reducir stake", descartar: "Descartado" };

function analysisBlock(a) {
  if (!a) return "";
  const adj = a.prob_adjust ? ` · ajuste ${a.prob_adjust > 0 ? "+" : ""}${(a.prob_adjust * 100).toFixed(1)} pts` : "";
  const src = (a.sources || [])
    .map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">[${i + 1}]</a>`)
    .join(" ");
  return `<div class="analysis">
    <span class="verdict">${esc(VERDICT[a.verdict] || a.verdict)}${adj}</span>
    <p>${esc(a.reason)} ${src}</p>
  </div>`;
}

let pollTimer = null;

function pickCard(p, i) {
  const ctx = [];
  ctx.push(`<span>${esc(fmtDate(p.kickoff))}</span>`);
  ctx.push(`<span>Prob. <b>${pct(p.prob)}</b></span>`);
  ctx.push(`<span>Cuota justa <b>${p.fair_odds.toFixed(2)}</b></span>`);
  ctx.push(`<span>Mercado <b>${pct(p.prob_market)}</b>${p.fair_source === "consenso" ? " (consenso)" : ""}</span>`);
  if (p.prob_model != null) ctx.push(`<span>Modelo <b>${pct(p.prob_model)}</b></span>`);
  if (p.xg_home != null) ctx.push(`<span>Goles esp. <b>${p.xg_home.toFixed(2)} – ${p.xg_away.toFixed(2)}</b></span>`);
  if (p.form_home) ctx.push(`<span>Forma ${form(p.form_home)} vs ${form(p.form_away)}</span>`);

  return `
  <article class="pick ${p.analysis ? "v-" + esc(p.analysis.verdict) : ""}">
    <div class="rank">${i + 1}</div>
    <div>
      <div class="league">${esc(p.league)} · ${esc(p.market)}</div>
      <div class="match">${esc(p.home)} – ${esc(p.away)}</div>
      <span class="sel">${esc(p.selection)}</span>
      <div class="details">${ctx.join("")}</div>
      ${analysisBlock(p.analysis)}
    </div>
    <div class="numbers">
      <div><div class="k">Cuota</div><div class="v">${p.odds.toFixed(2)}</div></div>
      <div><div class="k">Valor</div><div class="v edge">${p.edge >= 0 ? "+" : ""}${pct(p.edge)}</div></div>
      <div><div class="k">Stake</div><div class="v">${p.stake_pct.toFixed(1)}%</div></div>
      <div class="book">en ${esc(p.bookmaker)}</div>
    </div>
  </article>`;
}

function render(data) {
  const gen = new Date(data.generated_at).toLocaleString("es-ES");
  $("#meta").innerHTML = `Actualizado: ${esc(gen)}${data.credits_remaining != null ? `<br>Créditos Odds API: ${esc(data.credits_remaining)}` : ""}`;

  let banner = "";
  if (data.demo) {
    banner += `<div class="banner demo"><b>Modo demo:</b> datos ficticios. Añade <code>ODDS_API_KEY</code> (y <code>API_FOOTBALL_KEY</code>) en Render para usar datos reales.</div>`;
  }
  const an = data.analysis || {};
  if (an.status === "pending") {
    banner += `<div class="banner ai">🧠 El analista IA (Google Antigravity) está revisando noticias y bajas de cada partido… Esta página se actualizará sola en cuanto termine.</div>`;
  } else if (an.status === "done") {
    banner += `<div class="banner ai done">🧠 Picks revisados por el analista IA${an.source === "simulado" ? " <b>(simulado: añade GEMINI_API_KEY)</b>" : " (Google Antigravity)"}.${data.discarded?.length ? ` ${data.discarded.length} descartados.` : ""}</div>`;
  } else if (an.status === "error") {
    banner += `<div class="banner warn">El analista IA ha fallado (${esc(an.error)}). Se muestran los picks sin revisar.</div>`;
  }
  clearTimeout(pollTimer);
  if (an.status === "pending") pollTimer = setTimeout(load, 15000);

  if (data.warnings?.length) {
    banner += `<div class="banner warn">Avisos:<ul>${data.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
  }
  $("#banner").innerHTML = banner;

  const avgEdge = data.picks.length ? data.picks.reduce((a, p) => a + p.edge, 0) / data.picks.length : 0;
  $("#summary").innerHTML = [
    ["Partidos analizados", data.matches_analysed],
    ["Con valor", data.candidates],
    ["Picks", data.picks.length],
    ["Valor medio", data.picks.length ? "+" + pct(avgEdge) : "—"],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${esc(v)}</div></div>`).join("");

  $("#picks").innerHTML = data.picks.length
    ? data.picks.map(pickCard).join("")
    : `<div class="empty">Esta semana no hay selecciones que superen el umbral de valor (${pct(data.settings.min_edge)}). Mejor no apostar que forzarlo.</div>`;

  $("#discarded").innerHTML = data.discarded?.length
    ? `<details><summary>Descartados por el analista (${data.discarded.length})</summary><div class="picks">${data.discarded.map(pickCard).join("")}</div></details>`
    : "";
}

async function load() {
  try {
    const r = await fetch("/api/picks");
    if (!r.ok) throw new Error(r.status);
    render(await r.json());
  } catch (e) {
    $("#picks").innerHTML = `<div class="empty">No se pudieron cargar los picks (${esc(e.message)}).</div>`;
  }
}

$("#refresh-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  btn.textContent = "Actualizando…";
  try {
    const r = await fetch("/api/refresh", { method: "POST", headers: { "X-Refresh-Token": $("#token").value } });
    if (r.status === 401) throw new Error("token incorrecto");
    if (!r.ok) throw new Error(r.status);
    render(await r.json());
  } catch (err) {
    $("#banner").insertAdjacentHTML("afterbegin", `<div class="banner warn">Error al actualizar: ${esc(err.message)}</div>`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Actualizar ahora";
  }
});

load();
