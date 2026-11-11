"""Noticias recientes de cada partido, de fuentes gratuitas, para el analista IA.

- Google News RSS (gratis, sin clave): titulares de los últimos 7 días por equipo.
  No es una API oficial documentada: si Google la cambia, el analista sigue funcionando
  pero sin noticias (y lo dice en el aviso).
- Tavily (opcional, TAVILY_API_KEY, 1.000 créditos gratis/mes, 1 crédito por búsqueda básica):
  añade fragmentos del texto de las noticias del partido.
  Formato verificado en https://docs.tavily.com/api-reference/endpoint/search.md
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger("news")

GNEWS = "https://news.google.com/rss/search"
TAVILY = "https://api.tavily.com/search"
# Idioma de búsqueda por liga (LaLiga en castellano; el resto en inglés, edición UK)
LOCALES = {
    "LaLiga": {"hl": "es", "gl": "ES", "ceid": "ES:es", "extra": "lesión OR baja OR convocatoria"},
}
DEFAULT_LOCALE = {"hl": "en-GB", "gl": "GB", "ceid": "GB:en", "extra": "injury OR team news OR suspended"}


def parse_rss(xml_text: str, max_items: int, max_age_days: int = 7, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        src = item.find("source")
        date_s = item.findtext("pubDate")
        try:
            date = parsedate_to_datetime(date_s) if date_s else None
        except (TypeError, ValueError):
            date = None
        if date and now - date > timedelta(days=max_age_days):
            continue
        if title and link:
            out.append({
                "title": title,
                "source": src.text.strip() if src is not None and src.text else None,
                "date": date.date().isoformat() if date else None,
                "url": link,
            })
        if len(out) >= max_items:
            break
    return out


def google_news(client: httpx.Client, team: str, league: str, max_items: int = 5) -> list[dict]:
    loc = LOCALES.get(league, DEFAULT_LOCALE)
    q = f'"{team}" ({loc["extra"]}) when:7d'
    r = client.get(GNEWS, params={"q": q, "hl": loc["hl"], "gl": loc["gl"], "ceid": loc["ceid"]},
                   timeout=15, headers={"User-Agent": "Mozilla/5.0 (picks-con-valor)"})
    r.raise_for_status()
    return parse_rss(r.text, max_items)


def tavily_news(client: httpx.Client, home: str, away: str, api_key: str, max_items: int = 5) -> list[dict]:
    r = client.post(
        TAVILY,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": f"{home} vs {away} team news injuries suspensions",
              "topic": "news", "time_range": "week", "search_depth": "basic", "max_results": max_items},
        timeout=20,
    )
    r.raise_for_status()
    out = []
    for res in r.json().get("results", [])[:max_items]:
        out.append({
            "title": res.get("title"),
            "source": None,
            "date": (res.get("published_date") or "")[:16] or None,
            "url": res.get("url"),
            "snippet": (res.get("content") or "")[:500],
        })
    return out


def news_for_pick(client: httpx.Client, pick: dict, tavily_key: str = "") -> tuple[list[dict], list[str]]:
    """Noticias del partido (sin duplicados) + lista de errores para el aviso/log."""
    items, errors = [], []
    for team in (pick["home"], pick["away"]):
        try:
            items += [{**n, "team": team} for n in google_news(client, team, pick.get("league", ""))]
        except Exception as e:  # noqa: BLE001
            errors.append(f"Google News ({team}): {type(e).__name__}")
    if tavily_key:
        try:
            items += tavily_news(client, pick["home"], pick["away"], tavily_key)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Tavily: {type(e).__name__}")
    seen, unique = set(), []
    for n in items:
        key = (n.get("title") or "").lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(n)
    if errors:
        log.warning("Noticias %s - %s: %s", pick["home"], pick["away"], "; ".join(errors))
    return unique, errors
