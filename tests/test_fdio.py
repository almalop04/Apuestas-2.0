"""Tests con respuestas REALES de footballdata.io (tests/fixtures/fdio_*.json, LaLiga 2026/27)."""
import json
from pathlib import Path

import httpx

from app import fdio
from app.config import Settings
from app.stats import expected_goals, match_team

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / f"fdio_{name}.json").read_text())


def mock_client(routes: dict, calls: list):
    """routes: {path: fixture_name | callable(request) -> dict | (status, body)}"""
    def handler(request: httpx.Request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer k"
        path = request.url.path.removeprefix("/api/v1")
        r = routes.get(path)
        if r is None:
            return httpx.Response(404, text="<html>404 Not Found</html>")
        body = r(request) if callable(r) else load(r)
        if isinstance(body, tuple):
            return httpx.Response(body[0], json=body[1])
        return httpx.Response(200, json=body)
    return fdio.FdioClient(httpx.Client(transport=httpx.MockTransport(handler)), "k")


def test_current_season_from_standings():
    calls = []
    c = mock_client({"/leagues/10/standings": "standings"}, calls)
    sid, rows = c.current_season(10)
    assert sid == 117065 and len(rows) == 20
    assert c.requests_remaining == 996


def test_current_season_falls_back_to_seasons():
    calls = []
    c = mock_client({"/leagues/10/seasons": "seasons"}, calls)  # standings da 404 (HTML)
    sid, rows = c.current_season(10)
    assert sid == 117065 and rows == []  # el año más alto, no is_current


def test_pagination():
    calls = []
    page_body = load("matches_complete")

    def matches(req):
        page = int(req.url.params["page"])
        body = json.loads(json.dumps(page_body))
        body["meta"]["total_pages"] = 2
        body["meta"]["page"] = page
        return body

    c = mock_client({"/matches": matches}, calls)
    out = c.matches(league_id=10, season_id=117065, status="complete")
    assert len(out) == 6 and len(calls) == 2
    assert calls[0].url.params["limit"] == "100"


def test_error_html_raises():
    c = mock_client({}, [])
    try:
        c.get("/leagues/10/standings")
        assert False
    except fdio.FdioError as e:
        assert "no JSON" in str(e)


def test_ratings_from_real_matches():
    matches = load("matches_complete")["data"]
    standings = load("standings")["data"]["standings"]
    now = 1793538000 + 10 * 86400
    r = fdio.build_ratings(matches, standings, now=now)
    teams = r["teams"]
    madrid = teams["Real Madrid CF"]
    assert madrid is teams["Real Madrid"]  # nombre limpio de standings
    assert madrid["rank"] == 2 and madrid["form"] == "W"
    getafe = teams["Getafe Club de Futbol"]
    assert getafe["form"] == "W" and r["by_id"][263] is getafe
    # Madrid ganó fuera con más xG -> ataque fuera por encima de la media
    assert madrid["att_away"] > 1
    lam_h, lam_a = expected_goals(r, getafe, madrid)
    assert 0.3 < lam_h < 4 and 0.3 < lam_a < 4


def test_xg_zero_means_missing():
    m = load("matches_complete")["data"][0]
    old = json.loads(json.dumps(m))
    old["xg"] = {k: 0 for k in old["xg"]}
    r = fdio.build_ratings([old], [], now=old["date_unix"])
    # sin xG usa goles reales: Getafe 3-1
    assert r["avg_home"] == 3 and r["avg_away"] == 1


def test_prematch_xg_from_upcoming():
    pre = fdio.prematch_xg(load("matches_upcoming")["data"])
    assert pre[(255, 250)] == (1.7, 1.1)  # Athletic - Espanyol
    assert len(pre) == 3


def test_free_plan_odds_are_empty():
    """Documenta por qué las cuotas NO salen de footballdata.io en el plan gratuito."""
    odds = load("match_odds")["data"]["odds"]
    assert odds["match_winner"] == {"home": 0, "draw": 0, "away": 0}


def test_odds_api_names_match_fdio_names():
    standings = load("standings")["data"]["standings"]
    matches = []
    for i, row in enumerate(standings):  # un partido ficticio por equipo para tener todos
        other = standings[(i + 1) % len(standings)]["team"]
        matches.append({"status": "complete", "date_unix": 1, "score": {"home": 1, "away": 0},
                        "xg": {"home": 1, "away": 1},
                        "home_team": {"team_id": row["team"]["team_id"], "team_name": row["team"]["team_name"]},
                        "away_team": {"team_id": other["team_id"], "team_name": other["team_name"]}})
    teams = fdio.build_ratings(matches, standings, now=1)["teams"]
    for odds_name, team_id in [
        ("Barcelona", 77), ("Real Madrid", 78), ("Atlético Madrid", 109), ("Real Betis", 254),
        ("Real Sociedad", 260), ("Sevilla", 92), ("Athletic Bilbao", 255), ("Villarreal", 70),
        ("Deportivo La Coruña", 256), ("Racing Santander", 283), ("Celta Vigo", 251), ("Alavés", 247),
        ("Espanyol", 250), ("Rayo Vallecano", 261), ("Getafe", 263), ("CA Osasuna", 257),
        ("Levante", 262), ("Elche CF", 265), ("Valencia", 258), ("Málaga", 253),
    ]:
        found = match_team(odds_name, teams)
        assert found and found["id"] == team_id, (odds_name, found and found["name"])


def test_generate_with_fdio(monkeypatch):
    """Flujo completo con cuotas simuladas y footballdata.io simulado con fixtures reales."""
    from app import picks

    upcoming = load("matches_upcoming")
    standings = load("standings")
    completed = load("matches_complete")
    # La muestra se pidió con limit=3 (total_pages=5); con limit=100 cabe en 1 página
    completed["meta"]["total_pages"] = 1
    upcoming["meta"]["total_pages"] = 1
    # La muestra real solo trae 3 partidos; se añaden 2 con Athletic (255) y Espanyol (250) con el mismo formato
    base = completed["data"][0]
    for i, (h, a) in enumerate([((255, "Athletic Club Bilbao"), (92, "Sevilla FC")),
                                ((263, "Getafe Club de Futbol"), (250, "Reial Club Deportiu Espanyol"))]):
        m = json.loads(json.dumps(base))
        m["match_id"] += i + 1
        m["home_team"].update(team_id=h[0], team_name=h[1])
        m["away_team"].update(team_id=a[0], team_name=a[1])
        completed["data"].append(m)

    def matches(req):
        return completed if req.url.params.get("status") == "complete" else upcoming

    routes = {"/leagues/10/standings": lambda r: standings, "/matches": matches}

    calls = []
    fake = mock_client(routes, calls)

    ev = {"id": "e1", "commence_time": "2026-11-20T20:00:00Z", "home_team": "Athletic Bilbao",
          "away_team": "Espanyol", "bookmakers": [
              {"key": "pinnacle", "title": "Pinnacle", "markets": [
                  {"key": "h2h", "outcomes": [{"name": "Athletic Bilbao", "price": 1.9},
                                              {"name": "Draw", "price": 3.5}, {"name": "Espanyol", "price": 4.6}]}]},
              {"key": "bet365", "title": "Bet365", "markets": [
                  {"key": "h2h", "outcomes": [{"name": "Athletic Bilbao", "price": 2.2},
                                              {"name": "Draw", "price": 3.3}, {"name": "Espanyol", "price": 4.2}]}]}]}

    monkeypatch.setattr(picks, "LEAGUES", [{"code": "LALIGA", "key": "soccer_spain_la_liga",
                                             "name": "LaLiga", "fdio_id": 10}])
    monkeypatch.setattr(picks, "fetch_odds", lambda c, key, s: ([ev], "490"))
    monkeypatch.setattr(picks, "FdioClient", lambda http, key: fake)
    s = Settings(odds_api_key="o", fdio_key="k", gemini_api_key="", demo_env="0")
    data = picks.generate(s)
    assert data["fdio_remaining"] == 994
    p = data["picks"][0]
    assert p["selection"] == "Gana Athletic Bilbao" and p["prob_model"] is not None
    assert p["xg_pre_home"] == 1.7 and p["xg_pre_away"] == 1.1
    assert not any("sin emparejar" in w for w in data["warnings"]), data["warnings"]
    # clasificación + jugados + próximos = 3 peticiones por liga
    assert len(calls) == 3
