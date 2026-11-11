import json
from datetime import datetime, timezone

import httpx

from app import news

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>x</title>
<item><title>Tottenham sin Maddison ante el Ipswich - Marca</title><link>https://news.google.com/rss/articles/A1</link>
<pubDate>Tue, 10 Nov 2026 18:00:00 GMT</pubDate><source url="https://www.marca.com">Marca</source></item>
<item><title>Noticia vieja</title><link>https://news.google.com/rss/articles/OLD</link>
<pubDate>Tue, 20 Oct 2026 18:00:00 GMT</pubDate><source url="https://as.com">AS</source></item>
<item><title>Ipswich recupera a su portero</title><link>https://news.google.com/rss/articles/A2</link>
<pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


def test_parse_rss_filters_old_and_reads_fields():
    out = news.parse_rss(RSS, max_items=5, now=NOW)
    assert [n["title"] for n in out] == ["Tottenham sin Maddison ante el Ipswich - Marca", "Ipswich recupera a su portero"]
    assert out[0] == {"title": "Tottenham sin Maddison ante el Ipswich - Marca", "source": "Marca",
                      "date": "2026-11-10", "url": "https://news.google.com/rss/articles/A1"}
    assert out[1]["source"] is None


def test_google_news_query_locale_and_tavily_request(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if req.url.host == "news.google.com":
            return httpx.Response(200, text=RSS)
        assert req.headers["Authorization"] == "Bearer tvly-k"
        body = json.loads(req.content)
        assert body["topic"] == "news" and body["time_range"] == "week" and body["search_depth"] == "basic"
        return httpx.Response(200, json={"results": [
            {"title": "Ipswich recupera a su portero", "url": "https://t/1", "content": "x" * 900,
             "published_date": "2026-11-10"},
            {"title": "Previa Tottenham - Ipswich", "url": "https://t/2", "content": "previa", "published_date": None}]})

    monkeypatch.setattr(news, "parse_rss", _parse)  # fecha fija para que el filtro de 7 días sea estable
    client = httpx.Client(transport=httpx.MockTransport(handler))
    pick = {"home": "Tottenham Hotspur", "away": "Ipswich Town", "league": "Premier League"}
    items, errors = news.news_for_pick(client, pick, tavily_key="tvly-k")
    assert errors == []
    gn = [c for c in calls if c.url.host == "news.google.com"]
    assert len(gn) == 2 and gn[0].url.params["hl"] == "en-GB" and gn[0].url.params["ceid"] == "GB:en"
    assert '"Tottenham Hotspur"' in gn[0].url.params["q"] and "when:7d" in gn[0].url.params["q"]
    titles = [i["title"] for i in items]
    assert titles.count("Ipswich recupera a su portero") == 1  # sin duplicados entre fuentes
    assert "Previa Tottenham - Ipswich" in titles
    assert all(len(i.get("snippet", "")) <= 500 for i in items)


_orig_parse = news.parse_rss


def _parse(xml, n):
    return _orig_parse(xml, n, now=NOW)


def test_laliga_searches_in_spanish_and_errors_do_not_break():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    items, errors = news.news_for_pick(client, {"home": "Real Betis", "away": "Sevilla FC", "league": "LaLiga"})
    assert items == [] and len(errors) == 2
    assert calls[0].url.params["hl"] == "es" and "lesión" in calls[0].url.params["q"]
