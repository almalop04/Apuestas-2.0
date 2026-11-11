"""Analista IA: el agente de Google Antigravity (Gemini API) revisa los candidatos.

El agente NO calcula las probabilidades (eso lo hace el código). Busca contexto
(lesiones, rotaciones, motivación, noticias) y devuelve un veredicto por pick:
  mantener | reducir | descartar  + un ajuste pequeño de probabilidad + motivo.
El código aplica el ajuste con un tope (ANALYST_MAX_ADJUST) y recalcula el valor.
"""
import json
import logging
import random
import re
import time

from .config import Settings
from .model import kelly_stake

log = logging.getLogger("analyst")

TERMINAL = {"completed", "failed", "cancelled", "incomplete", "budget_exceeded", "requires_action"}

PROMPT = """Eres un analista de apuestas de fútbol riguroso y escéptico.
Tienes una lista de selecciones candidatas. Para cada una, un modelo estadístico ya ha calculado
la probabilidad ("prob") y el valor esperado ("edge") frente a la mejor cuota disponible.

Tu trabajo NO es recalcular probabilidades desde cero. Para CADA candidato:
1. Busca en Google noticias recientes (últimos 7 días) del partido y de ambos equipos:
   lesiones y sanciones de titulares, posibles rotaciones (partidos europeos o de copa cerca),
   motivación (descenso, objetivos, nada en juego), cambios de entrenador, clima extremo.
2. Decide si esa información cambia la probabilidad de la selección concreta.
3. Si no encuentras nada relevante, el veredicto es "mantener" con ajuste 0. No inventes noticias.

Devuelve ÚNICAMENTE un bloque JSON válido, sin texto adicional, con este formato:
```json
[
  {{"id": "c1", "verdict": "mantener|reducir|descartar", "prob_adjust": 0.0,
    "reason": "2-3 frases en castellano con los hechos concretos", "sources": ["https://..."]}}
]
```
Reglas:
- "prob_adjust" es el cambio en probabilidad absoluta, entre -{max_adj} y +{max_adj} (p. ej. -0.02).
- "descartar" solo con información concreta y verificada (p. ej. baja confirmada de una pieza clave).
- "reducir" si hay dudas razonables. Incluye las URLs que hayas usado.
- Un objeto por cada id recibido, sin omitir ninguno.

Fecha actual (UTC): {today}

Candidatos:
{candidates}
"""


def _candidate_payload(picks: list[dict]) -> list[dict]:
    keys = ("league", "home", "away", "kickoff", "selection", "odds", "bookmaker",
            "prob", "prob_market", "prob_model", "edge", "form_home", "form_away",
            "xg_home", "xg_away", "rank_home", "rank_away")
    return [{"id": f"c{i + 1}", **{k: p.get(k) for k in keys}} for i, p in enumerate(picks)]


def parse_verdicts(text: str) -> list[dict]:
    """Extrae la lista JSON de la respuesta (tolera texto o ```json alrededor)."""
    if not text:
        raise ValueError("respuesta vacía del agente")
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("["): text.rfind("]") + 1]
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("el agente no devolvió una lista")
    return data


def _run_antigravity(prompt: str, s: Settings) -> str:
    from google import genai  # import diferido: solo si se usa el analista

    # El agente solo existe en v1beta; la librería usa v1 por defecto (error 400 "only available in v1beta")
    ver = s.analyst_api_version
    client = genai.Client(api_key=s.gemini_api_key, http_options={"api_version": ver})
    interaction = client.interactions.create(
        agent=s.analyst_agent,
        input=prompt,
        environment="remote",
        tools=[{"type": "google_search"}, {"type": "url_context"}],
        background=True,
        api_version=ver,
    )
    deadline = time.time() + s.analyst_timeout
    while interaction.status not in TERMINAL:
        if time.time() > deadline:
            try:
                client.interactions.cancel(interaction.id, api_version=ver)
            except Exception:  # noqa: BLE001
                pass
            raise TimeoutError(f"el agente tardó más de {s.analyst_timeout:.0f} s")
        time.sleep(10)
        interaction = client.interactions.get(interaction.id, api_version=ver)
    if interaction.status != "completed":
        raise RuntimeError(f"estado del agente: {interaction.status} {interaction.errors or ''}")
    return interaction.output_text or ""


def _simulated(payload: list[dict], s: Settings) -> list[dict]:
    """Solo para modo demo sin clave: veredictos ficticios para ver la interfaz."""
    rng = random.Random(len(payload))
    out = []
    for c in payload:
        v = rng.choices(["mantener", "reducir", "descartar"], [6, 3, 1])[0]
        adj = {"mantener": 0.0, "reducir": -0.01, "descartar": -0.03}[v]
        out.append({"id": c["id"], "verdict": v, "prob_adjust": adj,
                    "reason": f"[Simulado] Ejemplo de análisis para {c['home']} – {c['away']}. "
                              "Con GEMINI_API_KEY aquí aparecerán las noticias reales.",
                    "sources": []})
    return out


def apply_verdicts(picks: list[dict], verdicts: list[dict], s: Settings) -> tuple[list[dict], list[dict]]:
    """Aplica los veredictos. Devuelve (picks válidos re-ordenados, descartados)."""
    by_id = {v.get("id"): v for v in verdicts if isinstance(v, dict)}
    kept, discarded = [], []
    for i, p in enumerate(picks):
        v = by_id.get(f"c{i + 1}")
        p = dict(p)
        if not v:
            p["analysis"] = {"verdict": "sin análisis", "reason": "El agente no devolvió veredicto.", "sources": []}
            kept.append(p)
            continue
        verdict = str(v.get("verdict", "mantener")).lower()
        try:
            adj = float(v.get("prob_adjust") or 0)
        except (TypeError, ValueError):
            adj = 0.0
        adj = max(-s.analyst_max_adjust, min(s.analyst_max_adjust, adj))
        prob = min(0.99, max(0.01, p["prob"] + adj))
        p.update(
            prob=round(prob, 4),
            fair_odds=round(1 / prob, 2),
            edge=round(prob * p["odds"] - 1, 4),
        )
        stake = kelly_stake(prob, p["odds"], s.kelly_fraction)
        if verdict == "reducir":
            stake /= 2
        p["stake_pct"] = round(stake, 2)
        p["analysis"] = {
            "verdict": verdict,
            "prob_adjust": round(adj, 4),
            "reason": str(v.get("reason", ""))[:600],
            "sources": [u for u in (v.get("sources") or []) if isinstance(u, str) and u.startswith("http")][:4],
        }
        if verdict == "descartar" or p["edge"] < s.min_edge or p["prob"] < s.min_prob:
            discarded.append(p)
        else:
            kept.append(p)
    kept.sort(key=lambda c: c["edge"], reverse=True)
    return kept[: s.num_picks], discarded


def _analyse_batch(batch: list[dict], s: Settings, today: str) -> list[dict]:
    if not s.gemini_api_key:
        time.sleep(s.analyst_demo_delay)  # solo para que la barra se vea en modo demo
        return _simulated(batch, s)
    prompt = PROMPT.format(
        max_adj=s.analyst_max_adjust, today=today,
        candidates=json.dumps(batch, ensure_ascii=False, indent=1),
    )
    return parse_verdicts(_run_antigravity(prompt, s))


def analyse(picks: list[dict], s: Settings, today: str, progress=None) -> tuple[list[dict], list[dict], str]:
    """Revisa los candidatos en lotes (en paralelo) e informa del progreso real.

    progress(done, total, errors) se llama cada vez que termina un lote.
    Si un lote falla, sus picks quedan "sin análisis"; si fallan todos, se lanza error.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    payload = _candidate_payload(picks)
    size = max(1, s.analyst_batch_size)
    batches = [payload[i:i + size] for i in range(0, len(payload), size)]
    verdicts: list[dict] = []
    errors: list[str] = []
    done = 0
    if progress:
        progress(0, len(payload), errors)
    with ThreadPoolExecutor(max_workers=max(1, s.analyst_concurrency)) as pool:
        futures = {pool.submit(_analyse_batch, b, s, today): b for b in batches}
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                verdicts.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                log.warning("Lote del analista fallido: %s", e)
                errors.append(str(e)[:200])
            done += len(batch)
            if progress:
                progress(done, len(payload), errors)
    if errors and len(errors) == len(batches):
        raise RuntimeError(errors[0])
    kept, discarded = apply_verdicts(picks, verdicts, s)
    return kept, discarded, ("antigravity" if s.gemini_api_key else "simulado")
