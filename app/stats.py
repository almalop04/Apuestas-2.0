"""Estadísticas de API-Football: fuerza de ataque/defensa, forma y goles esperados."""
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher

import httpx

BASE = "https://v3.football.api-sports.io"

# Nombres que difieren mucho entre The Odds API y API-Football
ALIASES = {
    "wolverhampton wanderers": "wolves",
    "brighton and hove albion": "brighton",
    "inter milan": "inter",
    "athletic bilbao": "athletic club",
    "bayern munich": "bayern munchen",
    "paris saint germain": "paris saint germain",
    "tottenham hotspur": "tottenham",
    "west ham united": "west ham",
    "newcastle united": "newcastle",
    "leeds united": "leeds",
    "nottingham forest": "nottingham forest",
    "atletico madrid": "atletico madrid",
    "celta vigo": "celta vigo",
    "alaves": "alaves",
    "as roma": "roma",
    "ss lazio": "lazio",
    "ssc napoli": "napoli",
    "borussia monchengladbach": "borussia monchengladbach",
    "1 fc koln": "1 fc koln",
    "fc cologne": "1 fc koln",
}

SHRINK_GAMES = 5  # partidos "virtuales" de media de liga para no sobrerreaccionar al principio
FORM_POINTS = {"W": 3, "D": 1, "L": 0}


def current_season(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def normalize(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", n)).strip()
    if n in ALIASES:
        return ALIASES[n]
    n = re.sub(r"\b(fc|cf|afc|sc|ac|ssc|club de futbol|calcio)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return ALIASES.get(n, n)


def match_team(name: str, candidates: dict[str, dict]) -> dict | None:
    """Empareja un nombre de equipo de las cuotas con la tabla de estadísticas."""
    target = normalize(name)
    best, best_score = None, 0.0
    for cand_name, data in candidates.items():
        c = normalize(cand_name)
        if c == target:
            return data
        score = SequenceMatcher(None, target, c).ratio()
        if target in c or c in target:
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = data, score
    return best if best_score >= 0.7 else None


def fetch_standings(client: httpx.Client, league_id: int, api_key: str, season: int | None = None) -> list[dict]:
    r = client.get(
        f"{BASE}/standings",
        params={"league": league_id, "season": season or current_season()},
        headers={"x-apisports-key": api_key},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"API-Football: {data['errors']}")
    resp = data.get("response") or []
    if not resp:
        raise RuntimeError("API-Football: sin clasificación para esta liga/temporada")
    return resp[0]["league"]["standings"][0]


def fetch_standings_footballdata(client: httpx.Client, league_id: int, api_key: str) -> list[dict]:
    """Obtiene la clasificación de footballdata.io y la adapta al formato común."""
    r = client.get(
        f"https://footballdata.io/api/v1/leagues/{league_id}/standings",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"footballdata.io: {data}")
    standings_raw = data.get("data", {}).get("standings", [])
    out = []
    for s in standings_raw:
        played = s.get("record", {}).get("matches_played", 0)
        h_played = max(1, played // 2)
        a_played = max(1, played - h_played)
        g_for = s.get("goals", {}).get("for", 0)
        g_against = s.get("goals", {}).get("against", 0)
        out.append({
            "team": {"name": s.get("team", {}).get("team_name")},
            "rank": s.get("position"),
            "form": "",
            "home": {
                "played": h_played,
                "goals": {"for": round(g_for * 0.55), "against": round(g_against * 0.45)},
            },
            "away": {
                "played": a_played,
                "goals": {"for": round(g_for * 0.45), "against": round(g_against * 0.55)},
            },
        })
    return out


def _form_ppg(form: str | None) -> float | None:
    if not form:
        return None
    last = [FORM_POINTS[c] for c in form[-5:] if c in FORM_POINTS]
    return sum(last) / len(last) if last else None


def build_ratings(standings: list[dict]) -> dict:
    """Calcula ratings por equipo a partir de la clasificación (goles en casa/fuera + forma)."""
    hp = sum(t["home"]["played"] for t in standings)
    ap = sum(t["away"]["played"] for t in standings)
    if hp == 0 or ap == 0:
        return {}
    avg_home_goals = sum(t["home"]["goals"]["for"] for t in standings) / hp
    avg_away_goals = sum(t["away"]["goals"]["for"] for t in standings) / ap

    def shrunk(goals: float, played: int, avg: float) -> float:
        return ((goals + SHRINK_GAMES * avg) / (played + SHRINK_GAMES)) / avg if avg else 1.0

    teams = {}
    for t in standings:
        h, a = t["home"], t["away"]
        teams[t["team"]["name"]] = {
            "name": t["team"]["name"],
            "rank": t.get("rank"),
            "form": (t.get("form") or "")[-5:],
            "form_ppg": _form_ppg(t.get("form")),
            "att_home": shrunk(h["goals"]["for"], h["played"], avg_home_goals),
            "def_home": shrunk(h["goals"]["against"], h["played"], avg_away_goals),
            "att_away": shrunk(a["goals"]["for"], a["played"], avg_away_goals),
            "def_away": shrunk(a["goals"]["against"], a["played"], avg_home_goals),
        }
    return {"avg_home": avg_home_goals, "avg_away": avg_away_goals, "teams": teams}


def _form_factor(ppg: float | None) -> float:
    """Ajuste suave por dinámica: ±7 % como máximo según puntos en los últimos 5 partidos."""
    if ppg is None:
        return 1.0
    return min(1.07, max(0.93, 1 + 0.05 * (ppg - 1.4) / 1.4))


def expected_goals(ratings: dict, home: dict, away: dict) -> tuple[float, float]:
    lam_h = ratings["avg_home"] * home["att_home"] * away["def_away"] * _form_factor(home["form_ppg"])
    lam_a = ratings["avg_away"] * away["att_away"] * home["def_home"] * _form_factor(away["form_ppg"])
    return lam_h, lam_a
