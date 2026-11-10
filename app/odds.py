"""Cliente de The Odds API (https://the-odds-api.com)."""
from datetime import datetime, timedelta, timezone

import httpx

from .config import Settings

BASE = "https://api.the-odds-api.com/v4"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_odds(client: httpx.Client, sport_key: str, s: Settings) -> tuple[list[dict], str | None]:
    """Devuelve (eventos, créditos restantes). Cada llamada gasta mercados × regiones créditos."""
    now = datetime.now(timezone.utc)
    r = client.get(
        f"{BASE}/sports/{sport_key}/odds",
        params={
            "apiKey": s.odds_api_key,
            "regions": s.regions,
            "markets": s.markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "commenceTimeFrom": _iso(now),
            "commenceTimeTo": _iso(now + timedelta(days=s.days_ahead)),
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json(), r.headers.get("x-requests-remaining")
