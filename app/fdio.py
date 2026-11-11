"""Cliente de footballdata.io y ratings de equipos a partir de goles + xG.

Formato verificado con respuestas reales de la API (ver tests/fixtures/fdio_*.json):
  - Base: https://footballdata.io/api/v1, cabecera  Authorization: Bearer <clave>
  - /leagues/{id}/standings  -> data.season.season_id + nombres limpios (team_name_clean).
    OJO: los campos home/away de standings vienen a 0, por eso NO se usan.
  - /matches?league_id&season_id&status=complete&page&limit -> partidos con
    score, xg (home/away + prematch_*), date_unix (UTC). Paginado: meta.total_pages.
  - Estado de partido: "complete" (jugado) / "incomplete" (programado).
  - /matches/{id}/odds viene todo a 0 en el plan gratuito -> las cuotas siguen
    saliendo de The Odds API.
"""
import time

import httpx

BASE = "https://footballdata.io/api/v1"
MAX_PAGES = 6
FORM_POINTS = {"W": 3, "D": 1, "L": 0}
SHRINK_GAMES = 4  # partidos "virtuales" de media de liga (evita sobrerreaccionar con pocos datos)


class FdioError(RuntimeError):
    pass


class FdioClient:
    def __init__(self, http: httpx.Client, api_key: str):
        self.http = http
        self.api_key = api_key
        self.requests_remaining: int | None = None

    def get(self, path: str, params: dict | None = None) -> dict:
        r = self.http.get(
            f"{BASE}{path}",
            params=params or {},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=25,
        )
        try:
            body = r.json()
        except ValueError:
            raise FdioError(f"{path}: respuesta no JSON (HTTP {r.status_code})") from None
        if r.status_code != 200 or not body.get("success", False):
            msg = body.get("error") or body.get("message") or body
            raise FdioError(f"{path}: HTTP {r.status_code} {str(msg)[:200]}")
        meta = body.get("meta") or {}
        if meta.get("requests_remaining") is not None:
            self.requests_remaining = meta["requests_remaining"]
        return body

    def current_season(self, league_id: int) -> tuple[int, list[dict]]:
        """Devuelve (season_id actual, filas de clasificación). Prueba standings y si falla, seasons."""
        try:
            data = self.get(f"/leagues/{league_id}/standings")["data"]
            return data["season"]["season_id"], data.get("standings") or []
        except (FdioError, KeyError, TypeError):
            seasons = self.get(f"/leagues/{league_id}/seasons")["data"]["seasons"]
            # is_current viene a true en todas las temporadas: se usa el año más alto
            latest = max(seasons, key=lambda s: s["year"])
            return latest["season_id"], []

    def matches(self, **params) -> list[dict]:
        out, page = [], 1
        while page <= MAX_PAGES:
            body = self.get("/matches", {**params, "page": page, "limit": 100})
            out.extend(body.get("data") or [])
            meta = body.get("meta") or {}
            total_pages = meta.get("total_pages") or (meta.get("pagination") or {}).get("total_pages") or 1
            if page >= total_pages:
                break
            page += 1
        return out


def _xg_available(m: dict) -> bool:
    xg = m.get("xg") or {}
    return (xg.get("home") or 0) + (xg.get("away") or 0) > 0


def build_ratings(completed: list[dict], standings: list[dict], *, now: float | None = None,
                  half_life_days: float = 75, xg_weight: float = 0.6) -> dict:
    """Ratings de ataque/defensa en casa y fuera.

    - Medida de cada partido: mezcla de xG y goles reales (xg_weight), o solo goles si no hay xG.
    - Los partidos recientes pesan más (semivida half_life_days) -> recoge la dinámica.
    - Forma: resultados de los últimos 5 partidos.
    """
    now = now or time.time()
    teams: dict[int, dict] = {}

    def team(t: dict) -> dict:
        tid = t["team_id"]
        if tid not in teams:
            teams[tid] = {
                "id": tid, "names": {t["team_name"]},
                "home": {"w": 0.0, "for": 0.0, "against": 0.0},
                "away": {"w": 0.0, "for": 0.0, "against": 0.0},
                "results": [],
            }
        return teams[tid]

    done = [m for m in completed if m.get("status") == "complete" and m.get("score")]
    done.sort(key=lambda m: m.get("date_unix") or 0)
    tot = {"home": 0.0, "away": 0.0, "w": 0.0}
    for m in done:
        sc, xg = m["score"], m.get("xg") or {}
        if _xg_available(m):
            hv = xg_weight * xg["home"] + (1 - xg_weight) * sc["home"]
            av = xg_weight * xg["away"] + (1 - xg_weight) * sc["away"]
        else:
            hv, av = sc["home"], sc["away"]
        days = max(0.0, (now - (m.get("date_unix") or now)) / 86400)
        w = 0.5 ** (days / half_life_days)
        h, a = team(m["home_team"]), team(m["away_team"])
        h["home"]["w"] += w; h["home"]["for"] += w * hv; h["home"]["against"] += w * av
        a["away"]["w"] += w; a["away"]["for"] += w * av; a["away"]["against"] += w * hv
        tot["home"] += w * hv; tot["away"] += w * av; tot["w"] += w
        res = "W" if sc["home"] > sc["away"] else "D" if sc["home"] == sc["away"] else "L"
        h["results"].append(res)
        a["results"].append({"W": "L", "L": "W", "D": "D"}[res])

    if tot["w"] == 0:
        return {}
    avg_home, avg_away = tot["home"] / tot["w"], tot["away"] / tot["w"]

    # Nombres alternativos y posición desde la clasificación
    rank = {}
    for row in standings:
        t = row.get("team") or {}
        tid = t.get("team_id")
        if tid in teams:
            for k in ("team_name", "team_name_clean", "full_name", "team_name_english"):
                if t.get(k):
                    teams[tid]["names"].add(t[k])
            rank[tid] = row.get("position")

    def rate(side: dict, key: str, avg: float) -> float:
        return ((side[key] + SHRINK_GAMES * avg) / (side["w"] + SHRINK_GAMES)) / avg if avg else 1.0

    by_name, by_id = {}, {}
    for tid, t in teams.items():
        last5 = t["results"][-5:]
        data = {
            "id": tid,
            "name": sorted(t["names"], key=len)[0],
            "rank": rank.get(tid),
            "form": "".join(last5),
            "form_ppg": sum(FORM_POINTS[r] for r in last5) / len(last5) if last5 else None,
            "att_home": rate(t["home"], "for", avg_home),
            "def_home": rate(t["home"], "against", avg_away),
            "att_away": rate(t["away"], "for", avg_away),
            "def_away": rate(t["away"], "against", avg_home),
        }
        by_id[tid] = data
        for n in t["names"]:
            by_name[n] = data
    return {"avg_home": avg_home, "avg_away": avg_away, "teams": by_name, "by_id": by_id}


def prematch_xg(upcoming: list[dict]) -> dict[tuple[int, int], tuple[float, float]]:
    """xG prepartido que publica footballdata.io para los próximos partidos."""
    out = {}
    for m in upcoming:
        xg = m.get("xg") or {}
        ph, pa = xg.get("prematch_home") or 0, xg.get("prematch_away") or 0
        if m.get("status") != "complete" and ph > 0 and pa > 0:
            out[(m["home_team"]["team_id"], m["away_team"]["team_id"])] = (ph, pa)
    return out


def league_ratings(client: FdioClient, league_id: int, days_ahead: int, **kw) -> dict:
    """3-4 peticiones por liga: clasificación + partidos jugados (paginado) + próximos."""
    season_id, standings = client.current_season(league_id)
    completed = client.matches(league_id=league_id, season_id=season_id, status="complete")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    until = time.strftime("%Y-%m-%d", time.gmtime(time.time() + days_ahead * 86400))
    upcoming = client.matches(league_id=league_id, season_id=season_id, **{"from": today, "to": until})
    ratings = build_ratings(completed, standings, **kw)
    if ratings:
        ratings["prematch"] = prematch_xg(upcoming)
        ratings["matches_used"] = len(completed)
    return ratings
