"""Utilidades comunes del modelo: emparejado de nombres entre APIs, ratings (modo demo) y goles esperados."""
import re
import unicodedata
from difflib import SequenceMatcher


# Nombres que difieren mucho entre The Odds API y footballdata.io
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
    # nombres largos de footballdata.io
    "reial club deportiu espanyol": "espanyol",
    "rcd espanyol": "espanyol",
    "real club deportivo de la coruna": "deportivo la coruna",
    "deportivo la coruna": "deportivo la coruna",
    "real racing club de santander": "racing santander",
    "real club celta de vigo": "celta vigo",
    "celta de vigo": "celta vigo",
    "getafe club de futbol": "getafe",
    "real sociedad de futbol": "real sociedad",
    "athletic club bilbao": "athletic club",
    "real betis balompie": "real betis",
    "fc internazionale milano": "inter",
    "internazionale milano": "inter",
    "fc bayern munchen": "bayern munchen",
    "club atletico de madrid": "atletico madrid",
    "rc celta de vigo": "celta vigo",
    "deportivo alaves": "alaves",
    "rcd espanyol de barcelona": "espanyol",
    "wolverhampton wanderers fc": "wolves",
    "brighton and hove albion fc": "brighton",
    "paris saint germain fc": "paris saint germain",
    "olympique de marseille": "marseille",
    "olympique lyonnais": "lyon",
}

SHRINK_GAMES = 5  # partidos "virtuales" de media de liga para no sobrerreaccionar al principio
FORM_POINTS = {"W": 3, "D": 1, "L": 0}


def normalize(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    n = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", n)).strip()
    if n in ALIASES:
        return ALIASES[n]
    n = re.sub(r"\b(fc|cf|afc|sc|ac|ssc|as|ss|club de futbol|calcio|rcd|cd|ud|sd|ca)\b", " ", n)
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
        data = {
            "name": t["team"]["name"],
            "rank": t.get("rank"),
            "form": (t.get("form") or "")[-5:],
            "form_ppg": _form_ppg(t.get("form")),
            "att_home": shrunk(h["goals"]["for"], h["played"], avg_home_goals),
            "def_home": shrunk(h["goals"]["against"], h["played"], avg_away_goals),
            "att_away": shrunk(a["goals"]["for"], a["played"], avg_away_goals),
            "def_away": shrunk(a["goals"]["against"], a["played"], avg_home_goals),
        }
        teams[t["team"]["name"]] = data
        for alt in (t["team"].get("shortName"), t["team"].get("tla")):
            if alt and alt not in teams:
                teams[alt] = data  # nombres alternativos para emparejar mejor
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
