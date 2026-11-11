"""Genera los picks: junta cuotas + estadísticas, calcula valor y guarda en caché."""
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import analyst, demo_data
from .config import LEAGUES, Settings
from .model import best_prices, kelly_stake, market_probabilities, poisson_probs
from .odds import fetch_odds
from .fdio import FdioClient, league_ratings
from .stats import build_ratings, expected_goals, match_team

log = logging.getLogger("picks")
CACHE_FILE = Path("/tmp/picks_cache.json")
_lock = threading.Lock()
_cache: dict | None = None


def _label(mid: str, name: str, ev: dict) -> str:
    if mid == "h2h":
        if name == "Draw":
            return "Empate"
        return f"Gana {name}"
    point = mid.split("_", 1)[1]
    return f"{'Más' if name == 'Over' else 'Menos'} de {point} goles"


def _model_key(mid: str, name: str, ev: dict) -> str | None:
    if mid == "h2h":
        return {ev["home_team"]: "home", ev["away_team"]: "away", "Draw": "draw"}.get(name)
    if mid == "totals_2.5":
        return {"Over": "over25", "Under": "under25"}.get(name)
    return None


def analyse_event(ev: dict, league: dict, ratings: dict | None, s: Settings) -> list[dict]:
    """Devuelve todas las selecciones con valor positivo de un partido."""
    fair = market_probabilities(ev, s.sharp_book)
    best = best_prices(ev, s.sharp_book)

    model, ctx = None, {}
    if ratings:
        home = match_team(ev["home_team"], ratings["teams"])
        away = match_team(ev["away_team"], ratings["teams"])
        if home and away and home is not away:
            lam_h, lam_a = expected_goals(ratings, home, away)
            pre = (ratings.get("prematch") or {}).get((home.get("id"), away.get("id")))
            if pre and s.prematch_weight > 0:
                # mezcla con el xG prepartido que publica footballdata.io
                w = s.prematch_weight
                lam_h, lam_a = (1 - w) * lam_h + w * pre[0], (1 - w) * lam_a + w * pre[1]
            model = poisson_probs(lam_h, lam_a)
            ctx = {
                "xg_home": round(lam_h, 2),
                "xg_away": round(lam_a, 2),
                "xg_pre_home": pre[0] if pre else None,
                "xg_pre_away": pre[1] if pre else None,
                "form_home": home["form"],
                "form_away": away["form"],
                "rank_home": home["rank"],
                "rank_away": away["rank"],
            }

    out = []
    for mid, fm in fair.items():
        for name, p_market in fm["probs"].items():
            offer = best.get(mid, {}).get(name)
            if not offer:
                continue
            mk = _model_key(mid, name, ev)
            p_model = model[mk] if (model and mk) else None
            if p_model is not None:
                prob = s.market_weight * p_market + (1 - s.market_weight) * p_model
            else:
                prob = p_market
            odds = offer["price"]
            edge = prob * odds - 1
            if edge < s.min_edge or not (s.min_odds <= odds <= s.max_odds) or prob < s.min_prob:
                continue
            if p_model is not None and abs(p_model - p_market) > s.max_model_gap:
                continue  # discrepancia demasiado grande: desconfiamos del modelo
            out.append(
                {
                    "league": league["name"],
                    "home": ev["home_team"],
                    "away": ev["away_team"],
                    "kickoff": ev["commence_time"],
                    "market": "1X2" if mid == "h2h" else "Goles",
                    "selection": _label(mid, name, ev),
                    "odds": round(odds, 2),
                    "bookmaker": offer["book"],
                    "prob": round(prob, 4),
                    "prob_market": round(p_market, 4),
                    "prob_model": round(p_model, 4) if p_model is not None else None,
                    "fair_odds": round(1 / prob, 2),
                    "edge": round(edge, 4),
                    "stake_pct": round(kelly_stake(prob, odds, s.kelly_fraction), 2),
                    "fair_source": fm["source"],
                    **ctx,
                }
            )
    return out


def generate(s: Settings) -> dict:
    warnings: list[str] = []
    candidates: list[dict] = []
    credits = None
    analysed = 0
    unmatched: list[str] = []

    with httpx.Client() as client:
        fdio = FdioClient(client, s.fdio_key) if (s.fdio_key and not s.demo) else None
        if not s.demo and not s.fdio_key:
            warnings.append("Sin FOOTBALLDATA_IO_KEY: picks calculados solo con el mercado, sin modelo de estadísticas")
        for league in LEAGUES:
            # 1) Cuotas
            if s.demo:
                events = demo_data.events(league)
            else:
                try:
                    events, credits = fetch_odds(client, league["key"], s)
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"{league['name']}: no se pudieron obtener cuotas ({e})")
                    continue
            if not events:
                continue

            # 2) Estadísticas (opcionales: si fallan se usa solo el mercado)
            ratings = None
            if s.demo:
                ratings = build_ratings(demo_data.standings(league))
            elif fdio:
                try:
                    ratings = league_ratings(
                        fdio, league["fdio_id"], s.days_ahead,
                        half_life_days=s.half_life_days, xg_weight=s.xg_weight,
                    ) or None
                    if ratings is None:
                        warnings.append(f"{league['name']}: footballdata.io sin partidos jugados, solo mercado")
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"{league['name']}: sin estadísticas, solo mercado ({e})")

            for ev in events:
                analysed += 1
                if ratings:
                    for side in ("home_team", "away_team"):
                        if not match_team(ev[side], ratings["teams"]):
                            unmatched.append(f"{ev[side]} ({league['name']})")
                candidates.extend(analyse_event(ev, league, ratings, s))

    if unmatched:
        warnings.append("Equipos sin emparejar con footballdata.io (se usa solo el mercado en sus partidos): "
                        + ", ".join(sorted(set(unmatched))))

    # 3) Una selección por partido (la de más valor) y top N
    by_match: dict[tuple, dict] = {}
    for c in candidates:
        k = (c["home"], c["away"], c["kickoff"])
        if k not in by_match or c["edge"] > by_match[k]["edge"]:
            by_match[k] = c
    ranked = sorted(by_match.values(), key=lambda c: c["edge"], reverse=True)
    pool = ranked[: max(s.num_picks, s.analyst_candidates)] if s.analyst else []
    picks = ranked[: s.num_picks]

    return {
        "analysis": {"status": "pending" if s.analyst and pool else "off", "source": None, "error": None},
        "pool": pool,
        "discarded": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo": s.demo,
        "matches_analysed": analysed,
        "candidates": len(by_match),
        "credits_remaining": credits,
        "fdio_remaining": fdio.requests_remaining if fdio else None,
        "warnings": warnings,
        "settings": {
            "min_edge": s.min_edge,
            "min_odds": s.min_odds,
            "max_odds": s.max_odds,
            "min_prob": s.min_prob,
            "max_model_gap": s.max_model_gap,
            "market_weight": s.market_weight,
            "kelly_fraction": s.kelly_fraction,
            "days_ahead": s.days_ahead,
            "xg_weight": s.xg_weight,
            "prematch_weight": s.prematch_weight,
        },
        "picks": picks,
    }


def _fresh(data: dict | None, s: Settings) -> bool:
    if not data:
        return False
    ts = datetime.fromisoformat(data["generated_at"]).timestamp()
    return time.time() - ts < s.cache_hours * 3600 and data.get("demo") == s.demo


_analysis_running = False


def _save() -> None:
    try:
        CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False))
    except OSError:
        pass


def _run_analysis(snapshot_id: str, pool: list[dict], s: Settings) -> None:
    """Hilo en segundo plano: el agente revisa los candidatos y actualiza la caché."""
    global _analysis_running
    started = datetime.now(timezone.utc).isoformat()

    def progress(done: int, total: int, errors: list[str]) -> None:
        with _lock:
            if _cache and _cache["generated_at"] == snapshot_id:
                _cache["analysis"]["progress"] = {
                    "done": done, "total": total, "failed_batches": len(errors), "started_at": started,
                }

    try:
        kept, discarded, source = analyst.analyse(
            pool, s, datetime.now(timezone.utc).date().isoformat(), progress=progress)
        result = {"status": "done", "source": source, "error": None}
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo del analista")
        kept, discarded = None, []
        result = {"status": "error", "source": None, "error": str(e)[:300]}
    with _lock:
        _analysis_running = False
        if not _cache or _cache["generated_at"] != snapshot_id:
            return  # los picks se regeneraron mientras tanto
        result["progress"] = _cache["analysis"].get("progress")
        _cache["analysis"] = result
        if kept is not None:
            _cache["picks"] = kept
            _cache["discarded"] = discarded
        _save()


def _maybe_start_analysis(s: Settings) -> None:
    global _analysis_running
    if _cache and _cache.get("analysis", {}).get("status") == "pending" and not _analysis_running:
        _analysis_running = True
        threading.Thread(
            target=_run_analysis, args=(_cache["generated_at"], list(_cache["pool"]), s), daemon=True
        ).start()


def get_picks(s: Settings, force: bool = False) -> dict:
    """Devuelve los picks en caché o los regenera si han caducado."""
    global _cache
    with _lock:
        if _cache is None and CACHE_FILE.exists():
            try:
                _cache = json.loads(CACHE_FILE.read_text())
            except Exception:  # noqa: BLE001
                _cache = None
        if force or not _fresh(_cache, s):
            _cache = generate(s)
            _save()
        _maybe_start_analysis(s)
        return json.loads(json.dumps({k: v for k, v in _cache.items() if k != "pool"}))  # copia
