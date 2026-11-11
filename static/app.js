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

function progressBar(pr) {
  if (!pr || !pr.total) return `<div class="progress"><div class="bar indeterminate"></div></div><div class="ptext">Preparando el análisis…</div>`;
  const pctDone = Math.round((pr.done / pr.total) * 100);
  const secs = Math.max(0, Math.round((Date.now() - new Date(pr.started_at)) / 1000));
  const t = secs >= 60 ? `${Math.floor(secs / 60)} min ${secs % 60} s` : `${secs} s`;
  return `<div class="progress"><div class="bar" style="width:${pctDone}%"></div></div>
    <div class="ptext">${pr.done} de ${pr.total} picks revisados · ${pctDone} % · ${t}${pr.failed_batches ? ` · ${pr.failed_batches} lote(s) con error` : ""}</div>`;
}

function pickCard(p, i) {
  const ctx = [];
  ctx.push(`<span>${esc(fmtDate(p.kickoff))}</span>`);
  ctx.push(`<span>Prob. <b>${pct(p.prob)}</b></span>`);
  ctx.push(`<span>Cuota justa <b>${p.fair_odds.toFixed(2)}</b></span>`);
  ctx.push(`<span>Mercado <b>${pct(p.prob_market)}</b>${p.fair_source === "consenso" ? " (consenso)" : ""}</span>`);
  if (p.prob_model != null) ctx.push(`<span>Modelo <b>${pct(p.prob_model)}</b></span>`);
  if (p.xg_home != null) ctx.push(`<span>Goles esp. <b>${p.xg_home.toFixed(2)} – ${p.xg_away.toFixed(2)}</b></span>`);
  if (p.xg_pre_home != null) ctx.push(`<span>xG prepartido fdio <b>${p.xg_pre_home.toFixed(2)} – ${p.xg_pre_away.toFixed(2)}</b></span>`);
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
  $("#meta").innerHTML = `Actualizado: ${esc(gen)}${data.credits_remaining != null ? `<br>Créditos Odds API: ${esc(data.credits_remaining)}` : ""}${data.fdio_remaining != null ? `<br>Peticiones footballdata.io: ${esc(data.fdio_remaining)}` : ""}`;

  let banner = "";
  if (data.demo) {
    banner += `<div class="banner demo"><b>Modo demo:</b> datos ficticios. Falta <code>ODDS_API_KEY</code> (cuotas, the-odds-api.com) en Render → Environment. Añádela y redespliega para usar datos reales.</div>`;
  }
  const an = data.analysis || {};
  if (an.status === "pending") {
    banner += `<div class="banner ai">🧠 El analista IA está revisando noticias y bajas de cada partido…${progressBar(an.progress)}</div>`;
  } else if (an.status === "done") {
    const failed = an.progress?.failed_batches ? ` ${an.progress.failed_batches} lote(s) fallaron: esos picks aparecen "sin análisis".` : "";
    banner += `<div class="banner ai done">🧠 Picks revisados por el analista IA${({ simulado: " <b>(simulado: añade GEMINI_API_KEY)</b>", antigravity: " (agente Google Antigravity)", gemini: " (Gemini + noticias de la semana)" })[an.source] || ""}.${data.discarded?.length ? ` ${data.discarded.length} descartados.` : ""}${failed}</div>`;
  } else if (an.status === "error") {
    banner += `<div class="banner warn">El analista IA ha fallado (${esc(an.error)}). Se muestran los picks sin revisar.</div>`;
  }
  clearTimeout(pollTimer);
  if (an.status === "pending") pollTimer = setTimeout(load, 5000);

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
    : data.matches_analysed === 0
      ? `<div class="empty">No hay partidos con cuotas en los próximos ${esc(data.settings.days_ahead)} días (¿parón internacional?). Prueba a subir <code>DAYS_AHEAD</code> en Render.</div>`
      : `<div class="empty">Se han analizado ${esc(data.matches_analysed)} partidos y ninguna selección supera el umbral de valor (${pct(data.settings.min_edge)}). Mejor no apostar que forzarlo.</div>`;

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

const refreshMsg = (text, ok) => {
  $("#refresh-msg").className = ok ? "ok" : "err";
  $("#refresh-msg").textContent = text;
};

// Muestra cuántos caracteres hay en el campo (sin mostrar el token): así se ve si el navegador lo ha vaciado
$("#token").addEventListener("input", () => {
  const n = $("#token").value.trim().length;
  $("#token-count").textContent = n ? `${n} caracteres escritos` : "";
});

$("#refresh-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const token = $("#token").value.trim();
  if (!token) {
    refreshMsg("El campo está vacío: escribe el token antes de pulsar el botón.", false);
    return;
  }
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  btn.textContent = "Actualizando…";
  refreshMsg(`Enviando token de ${token.length} caracteres…`, true);
  try {
    const r = await fetch("/api/refresh", { method: "POST", headers: { "X-Refresh-Token": token } });
    if (r.status === 401) {
      const detail = (await r.json().catch(() => ({}))).detail;
      if (detail && typeof detail === "object") {
        throw new Error(detail.received_length
          ? `token incorrecto: han llegado ${detail.received_length} caracteres con huella ${detail.received_fingerprint} (compárala con /health)`
          : "token incorrecto: al servidor ha llegado vacío");
      }
      throw new Error("token incorrecto (el servidor tiene una versión anterior del código: espera a que Render termine de desplegar)");
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    render(await r.json());
    refreshMsg("✓ Actualizado. Si el analista está activo, la barra de progreso aparecerá arriba.", true);
  } catch (err) {
    refreshMsg(`Error al actualizar: ${err.message}`, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "Actualizar ahora";
  }
});

load();
