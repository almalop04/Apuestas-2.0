"""Datos ficticios para probar la web sin claves de API (modo demo)."""
import random
from datetime import datetime, timedelta, timezone

from .model import poisson_probs

TEAMS = {
    "soccer_spain_la_liga": [
        ("Real Madrid", 2.3, 0.8), ("Barcelona", 2.4, 0.9), ("Atlético Madrid", 1.7, 0.8),
        ("Athletic Bilbao", 1.5, 1.0), ("Villarreal", 1.6, 1.2), ("Real Betis", 1.4, 1.2),
        ("Real Sociedad", 1.2, 1.1), ("Sevilla", 1.1, 1.4), ("Valencia", 1.0, 1.3), ("Getafe", 0.9, 1.1),
    ],
    "soccer_epl": [
        ("Arsenal", 2.1, 0.7), ("Liverpool", 2.2, 1.0), ("Manchester City", 2.0, 1.0),
        ("Chelsea", 1.8, 1.1), ("Newcastle United", 1.6, 1.1), ("Tottenham Hotspur", 1.6, 1.5),
        ("Aston Villa", 1.4, 1.2), ("Brighton and Hove Albion", 1.4, 1.3),
        ("Wolverhampton Wanderers", 1.0, 1.6), ("Everton", 1.0, 1.3),
    ],
    "soccer_italy_serie_a": [
        ("Inter Milan", 2.1, 0.8), ("Napoli", 1.7, 0.8), ("AC Milan", 1.7, 1.0), ("Juventus", 1.5, 0.8),
        ("Atalanta BC", 1.8, 1.1), ("AS Roma", 1.4, 1.0), ("Lazio", 1.3, 1.1), ("Torino", 1.0, 1.2),
    ],
}

BOOKS = [
    ("pinnacle", "Pinnacle", 0.025, 0.0),
    ("bet365", "Bet365", 0.06, 0.05),
    ("williamhill", "William Hill", 0.065, 0.05),
    ("unibet_eu", "Unibet", 0.06, 0.06),
    ("marathonbet", "Marathonbet", 0.045, 0.05),
    ("betsson", "Betsson", 0.06, 0.06),
]


def _rng(key: str) -> random.Random:
    year, week, _ = datetime.now(timezone.utc).isocalendar()
    return random.Random(f"{key}-{year}-{week}")


def _prices(probs: dict, margin: float, noise: float, rng: random.Random) -> dict:
    out = {}
    for k, p in probs.items():
        q = p * (1 + margin) * (1 + rng.uniform(-noise, noise))
        out[k] = round(max(1.01, 1 / q), 2)
    return out


def events(league: dict) -> list[dict]:
    teams = TEAMS.get(league["key"])
    if not teams:
        return []
    rng = _rng(league["key"])
    order = teams[:]
    rng.shuffle(order)
    now = datetime.now(timezone.utc)
    out = []
    for i in range(0, len(order) - 1, 2):
        (h, ha, hd), (a, aa, ad) = order[i], order[i + 1]
        lam_h, lam_a = ha * ad / 1.25 * 1.1, aa * hd / 1.25 * 0.9
        p = poisson_probs(lam_h, lam_a)
        bookmakers = []
        for key, title, margin, noise in BOOKS:
            h2h = _prices({h: p["home"], "Draw": p["draw"], a: p["away"]}, margin, noise, rng)
            tot = _prices({"Over": p["over25"], "Under": p["under25"]}, margin, noise, rng)
            bookmakers.append(
                {
                    "key": key,
                    "title": title,
                    "markets": [
                        {"key": "h2h", "outcomes": [{"name": n, "price": v} for n, v in h2h.items()]},
                        {"key": "totals", "outcomes": [{"name": n, "price": v, "point": 2.5} for n, v in tot.items()]},
                    ],
                }
            )
        kickoff = now + timedelta(days=1 + i // 2, hours=rng.choice([0, 2, 4]))
        out.append(
            {
                "id": f"demo-{league['key']}-{i}",
                "commence_time": kickoff.strftime("%Y-%m-%dT%H:00:00Z"),
                "home_team": h,
                "away_team": a,
                "bookmakers": bookmakers,
            }
        )
    return out


def standings(league: dict) -> list[dict]:
    teams = TEAMS.get(league["key"], [])
    rng = _rng("st-" + league["key"])
    rows = []
    for i, (name, att, dfn) in enumerate(sorted(teams, key=lambda t: t[1] - t[2], reverse=True)):
        noise = lambda: rng.uniform(0.85, 1.15)  # noqa: E731
        rows.append(
            {
                "rank": i + 1,
                "team": {"name": name.replace(" Milan", "").replace(" Bilbao", " Club") if name in ("Inter Milan", "Athletic Bilbao") else name},
                "form": "".join(rng.choice("WWDL" if att > dfn else "WDLL") for _ in range(5)),
                "home": {"played": 6, "goals": {"for": round(att * 6 * 1.1 * noise()), "against": round(dfn * 6 * 0.9 * noise())}},
                "away": {"played": 6, "goals": {"for": round(att * 6 * 0.9 * noise()), "against": round(dfn * 6 * 1.1 * noise())}},
            }
        )
    return rows
