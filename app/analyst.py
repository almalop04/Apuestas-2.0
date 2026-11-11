"""Analista IA: Gemini con búsqueda de Google (por defecto) o el agente de Google Antigravity.

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

class Cancelled(Exception):
    """El análisis ya no hace falta (los picks se regeneraron mientras tanto)."""


TERMINAL = {"completed", "failed", "cancelled", "incomplete", "budget_exceeded", "requires_action"}
# Pausa por límite de texto generado: se reanuda con continuation_token (ver librería google-genai)
CONTINUE = "requires_continuation"
MAX_CONTINUATIONS = 3

PROMPT = """Eres un analista de apuestas de fútbol riguroso y escéptico.
Tienes una lista de selecciones candidatas. Para cada una, un modelo estadístico ya ha calculado
la probabilidad ("prob") y el valor esperado ("edge") frente a la mejor cuota disponible.

Tu trabajo NO es recalcular probabilidades desde cero. Para CADA candidato:
1. Busca en Google noticias recientes (últimos 7 días) del partido y de ambos equipos:
   lesiones y sanciones de titulares, posibles rotaciones (partidos europeos o de copa cerca),
   motivación (descenso, objetivos, nada en juego), cambios de entrenador, clima extremo.
2. Decide si esa información cambia la probabilidad de la selección concreta.
3. Si no encuentras nada relevante, el veredicto es "mantener" con ajuste 0. No inventes noticias.

Límites de esfuerzo (importante, hay un tiempo máximo):
- Como máximo 3 búsquedas por candidato y lee como mucho 2 páginas por candidato.
- No ejecutes código ni crees archivos: no hace falta.
- Las URLs de "sources" deben ser páginas que hayas consultado de verdad; si no tienes, deja la lista vacía.
- En cuanto tengas lo esencial, responde. Es mejor un "mantener" prudente que agotar el tiempo.

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


PROMPT_NEWS = """Eres un analista de apuestas de fútbol riguroso y escéptico.
Tienes una lista de selecciones candidatas. Para cada una, un modelo estadístico ya ha calculado
la probabilidad ("prob") y el valor esperado ("edge") frente a la mejor cuota disponible.
Cada candidato incluye en "noticias" los titulares (y a veces fragmentos) de los últimos 7 días
sobre los dos equipos, sacados de Google News y otras fuentes.

Tu trabajo NO es recalcular probabilidades desde cero. Para CADA candidato:
1. Lee SOLO sus "noticias": lesiones y sanciones de titulares, posibles rotaciones,
   motivación, cambios de entrenador, clima extremo.
2. Decide si esa información cambia la probabilidad de la selección concreta.
3. Si las noticias no dicen nada relevante (o no hay), el veredicto es "mantener" con ajuste 0.
   No uses conocimiento propio sobre plantillas o lesiones: puede estar desactualizado. No inventes.

Devuelve ÚNICAMENTE un bloque JSON válido, sin texto adicional, con este formato:
```json
[
  {{"id": "c1", "verdict": "mantener|reducir|descartar", "prob_adjust": 0.0,
    "reason": "2-3 frases en castellano con los hechos concretos", "sources": ["https://..."]}}
]
```
Reglas:
- "prob_adjust" es el cambio en probabilidad absoluta, entre -{max_adj} y +{max_adj} (p. ej. -0.02).
- "descartar" solo con información concreta de las noticias (p. ej. baja confirmada de una pieza clave).
- "reducir" si hay dudas razonables.
- "sources": SOLO URLs que aparezcan en las "noticias" de ese candidato y que hayas usado.
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


def describe(interaction) -> str:
    """Resumen de lo que ha hecho el agente: pasos por tipo, último paso y tokens."""
    steps = getattr(interaction, "steps", None) or []
    counts: dict[str, int] = {}
    for st in steps:
        t = getattr(st, "type", None) or type(st).__name__
        counts[t] = counts.get(t, 0) + 1
    parts = [f"{len(steps)} pasos"]
    if counts:
        parts.append(", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
        last = steps[-1]
        last_t = getattr(last, "type", None) or type(last).__name__
        summary = getattr(last, "summary", None)
        parts.append(f"último={last_t}" + (f" ({str(summary)[:80]})" if summary else ""))
    usage = getattr(interaction, "usage", None)
    total = getattr(usage, "total_tokens", None) if usage else None
    if total is not None:
        parts.append(f"tokens={total}")
    # Si no hay pasos: ¿Google sigue actualizando la interacción? ¿tiene ya máquina asignada?
    updated = getattr(interaction, "updated", None)
    if updated:
        parts.append(f"updated={updated}")
    if hasattr(interaction, "environment_id"):
        parts.append(f"entorno={getattr(interaction, 'environment_id', None) or 'sin asignar'}")
    return " · ".join(parts)


def probe_stream(client, interaction_id: str, ver: str, seconds: float = 20) -> str:
    """Escucha en directo los eventos del agente durante unos segundos (diagnóstico).

    Devuelve un resumen: tipos de evento recibidos, o "sin eventos" si no llega nada.
    """
    counts: dict[str, int] = {}
    start = time.time()
    note = ""
    stream = None
    try:
        stream = client.interactions.get(interaction_id, stream=True, api_version=ver, timeout=seconds)
        for ev in stream:
            t = getattr(ev, "event_type", None) or type(ev).__name__
            counts[t] = counts.get(t, 0) + 1
            if time.time() - start > seconds:
                break
    except Exception as e:  # noqa: BLE001  (un timeout de lectura = no llegó nada)
        note = type(e).__name__
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
    if not counts:
        return f"sin eventos en {int(time.time() - start)} s" + (f" ({note})" if note else "")
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])) + (
        f" · cortado por {note}" if note else "")


def _run_antigravity(prompt: str, s: Settings, should_stop=None, label: str = "") -> str:
    from google import genai  # import diferido: solo si se usa el analista

    # El agente solo existe en v1beta; la librería usa v1 por defecto (error 400 "only available in v1beta")
    ver = s.analyst_api_version
    client = genai.Client(api_key=s.gemini_api_key, http_options={"api_version": ver})
    base = dict(agent=s.analyst_agent, environment="remote", background=True)
    tools = [{"type": t.strip()} for t in s.analyst_tools.split(",") if t.strip()]
    if tools:  # vacío = herramientas por defecto del agente
        base["tools"] = tools
    agent_config = {"type": "antigravity"}
    if s.analyst_max_tokens > 0:
        agent_config["max_total_tokens"] = s.analyst_max_tokens  # tope de tokens de toda la ejecución
    if s.analyst_agent_model:
        agent_config["model"] = s.analyst_agent_model
    if len(agent_config) > 1:
        base["agent_config"] = agent_config
    interaction = client.interactions.create(input=prompt, api_version=ver, **base)
    start = time.time()
    deadline = start + s.analyst_timeout
    continuations = 0
    last_logged = None
    next_probe = 90  # primera escucha en directo al minuto y medio
    log.info("Antigravity %s: creado %s (%s) · herramientas=%s · %s", label, interaction.id,
             interaction.status, s.analyst_tools or "por defecto", describe(interaction))

    def stop(exc: Exception):
        try:
            client.interactions.cancel(interaction.id, api_version=ver)
        except Exception:  # noqa: BLE001
            pass
        raise exc

    while interaction.status not in TERMINAL:
        if interaction.status == CONTINUE and getattr(interaction, "continuation_token", None):
            continuations += 1
            if continuations > MAX_CONTINUATIONS:
                stop(RuntimeError(f"el agente pidió continuar más de {MAX_CONTINUATIONS} veces"))
            log.info("Antigravity %s: reanudando %s (continuación %d)", label, interaction.id, continuations)
            interaction = client.interactions.create(
                continuation_token=interaction.continuation_token,
                previous_interaction_id=interaction.id, api_version=ver, **base)
            continue
        if should_stop and should_stop():
            stop(Cancelled())
        if time.time() > deadline:
            log.warning("Antigravity %s: tiempo agotado · %s", label, describe(interaction))
            stop(TimeoutError(f"el agente tardó más de {s.analyst_timeout:.0f} s "
                              f"(último estado: {interaction.status}; {describe(interaction)})"))
        elapsed = int(time.time() - start)
        if s.analyst_probe_every > 0 and elapsed >= next_probe:
            next_probe = elapsed + s.analyst_probe_every
            log.info("Antigravity %s: escucha en directo · %s", label, probe_stream(client, interaction.id, ver))
        if (interaction.status, elapsed // 60) != last_logged:  # como mucho 1 línea por minuto o cambio de estado
            last_logged = (interaction.status, elapsed // 60)
            log.info("Antigravity %s: %s · %d min %02d s · %s · id %s",
                     label, interaction.status, elapsed // 60, elapsed % 60, describe(interaction), interaction.id)
        time.sleep(10)
        interaction = client.interactions.get(interaction.id, api_version=ver)
    log.info("Antigravity %s: terminado con estado %s en %d s · %s",
             label, interaction.status, int(time.time() - start), describe(interaction))
    if interaction.status == "budget_exceeded":
        raise RuntimeError(f"el agente agotó el límite de tokens (ANALYST_MAX_TOKENS={s.analyst_max_tokens})")
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


def _gemini_once(client, types, model: str, prompt: str, s: Settings, google_search: bool, thinking: str | None):
    cfg = {"temperature": 0.2}
    if google_search:
        cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if thinking:
        # Menos razonamiento = respuesta más rápida (el 504 DEADLINE_EXCEEDED venía de pensar demasiado)
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=thinking.upper())
    return client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(**cfg))


def _run_gemini(prompt: str, s: Settings, label: str = "", google_search: bool = True) -> str:
    """Llamada normal a un modelo Gemini (sin agente). Con google_search=True usa la búsqueda
    de Google integrada (de pago en Gemini 3); con False solo lee las noticias que le pasamos (gratis).

    Si el modelo principal falla por saturación o tiempo (5xx, 429), reintenta con ANALYST_FALLBACK_MODEL.
    """
    from google import genai  # import diferido
    from google.genai import errors, types

    client = genai.Client(
        api_key=s.gemini_api_key,
        http_options={"api_version": s.analyst_api_version, "timeout": int(s.analyst_timeout * 1000)},
    )
    thinking = s.analyst_thinking if s.analyst_thinking not in ("", "none", "default") else None
    models = [s.analyst_model] + ([s.analyst_fallback_model]
                                  if s.analyst_fallback_model and s.analyst_fallback_model != s.analyst_model else [])
    last_error: Exception | None = None
    for model in models:
        start = time.time()
        log.info("Gemini %s: consultando %s %s · razonamiento=%s", label, model,
                 "con búsqueda de Google" if google_search else "con noticias de Google News", thinking or "por defecto")
        try:
            try:
                resp = _gemini_once(client, types, model, prompt, s, google_search, thinking)
            except errors.ClientError as e:
                if thinking and e.code == 400 and "thinking" in str(e).lower():
                    log.info("Gemini %s: %s no admite thinking_level, reintento sin él", label, model)
                    resp = _gemini_once(client, types, model, prompt, s, google_search, None)
                else:
                    raise
        except (errors.ServerError, errors.ClientError) as e:
            retryable = isinstance(e, errors.ServerError) or getattr(e, "code", None) == 429
            log.warning("Gemini %s: %s falló en %.0f s (%s)%s", label, model, time.time() - start,
                        str(e)[:160], " · pruebo el modelo de respaldo" if retryable and model != models[-1] else "")
            last_error = e
            if retryable:
                continue
            raise
        queries, sources = [], []
        try:
            gm = resp.candidates[0].grounding_metadata
            queries = list(gm.web_search_queries or [])
            sources = [c.web.uri for c in (gm.grounding_chunks or []) if getattr(c, "web", None) and c.web.uri]
        except (AttributeError, IndexError, TypeError):
            pass
        usage = getattr(resp, "usage_metadata", None)
        log.info("Gemini %s: respuesta de %s en %.1f s · %d búsquedas · %d fuentes · tokens=%s",
                 label, model, time.time() - start, len(queries), len(sources),
                 getattr(usage, "total_token_count", "?"))
        text = resp.text or ""
        if not text:
            raise RuntimeError(f"Gemini ({model}) devolvió una respuesta vacía")
        return text
    raise last_error or RuntimeError("Gemini no respondió")


def _analyse_batch(batch: list[dict], s: Settings, today: str, should_stop=None) -> list[dict]:
    if should_stop and should_stop():
        raise Cancelled()
    if not s.gemini_api_key:
        time.sleep(s.analyst_demo_delay)  # solo para que la barra se vea en modo demo
        return _simulated(batch, s)
    label = ",".join(c["id"] for c in batch)
    if s.analyst_provider == "antigravity":
        prompt = PROMPT.format(max_adj=s.analyst_max_adjust, today=today,
                               candidates=json.dumps(batch, ensure_ascii=False, indent=1))
        return parse_verdicts(_run_antigravity(prompt, s, should_stop, label=label))
    if s.analyst_search == "google":
        prompt = PROMPT.format(max_adj=s.analyst_max_adjust, today=today,
                               candidates=json.dumps(batch, ensure_ascii=False, indent=1))
        return parse_verdicts(_run_gemini(prompt, s, label=label, google_search=True))
    # Modo gratuito: buscamos nosotros las noticias y Gemini solo las lee
    import httpx

    from .news import news_for_pick
    enriched, total, failed = [], 0, 0
    with httpx.Client(follow_redirects=True) as http:
        for c in batch:
            items, errors = news_for_pick(http, c, s.tavily_key)
            total += len(items)
            failed += bool(errors)
            enriched.append({**c, "noticias": items[: s.analyst_news_per_pick]})
    log.info("Noticias %s: %d titulares (%d partidos con errores de búsqueda)", label, total, failed)
    prompt = PROMPT_NEWS.format(max_adj=s.analyst_max_adjust, today=today,
                                candidates=json.dumps(enriched, ensure_ascii=False, indent=1))
    return parse_verdicts(_run_gemini(prompt, s, label=label, google_search=False))


def analyse(picks: list[dict], s: Settings, today: str, progress=None,
            should_stop=None) -> tuple[list[dict], list[dict], str]:
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
        futures = {pool.submit(_analyse_batch, b, s, today, should_stop=should_stop): b for b in batches}
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                verdicts.extend(fut.result())
            except Cancelled:
                for f in futures:
                    f.cancel()
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("Lote del analista fallido: %s", e)
                errors.append(str(e)[:200])
            done += len(batch)
            if progress:
                progress(done, len(payload), errors)
    if errors and len(errors) == len(batches):
        raise RuntimeError(errors[0])
    kept, discarded = apply_verdicts(picks, verdicts, s)
    return kept, discarded, (s.analyst_provider if s.gemini_api_key else "simulado")
