"""Cálculos: quitar margen, probabilidades de mercado, modelo Poisson, valor y Kelly."""
from math import exp, factorial
from statistics import mean

from .config import EXCLUDED_BOOKS


def devig(prices: dict[str, float]) -> dict[str, float]:
    """Convierte cuotas en probabilidades sin margen (normalización proporcional)."""
    implied = {k: 1.0 / v for k, v in prices.items() if v and v > 1.0}
    total = sum(implied.values())
    if not implied or total <= 0:
        return {}
    return {k: p / total for k, p in implied.items()}


def market_id(market: dict) -> str | None:
    """Identificador del mercado: 'h2h' o 'totals_2.5'."""
    key = market.get("key")
    if key == "h2h":
        return "h2h"
    if key == "totals":
        points = {o.get("point") for o in market.get("outcomes", [])}
        if len(points) == 1:
            return f"totals_{points.pop()}"
    return None


def _book_markets(book: dict) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for m in book.get("markets", []):
        mid = market_id(m)
        if mid:
            out[mid] = {o["name"]: float(o["price"]) for o in m.get("outcomes", [])}
    return out


def market_probabilities(event: dict, sharp_book: str) -> dict[str, dict]:
    """Probabilidad 'justa' por mercado.

    Si la casa sharp (Pinnacle) cotiza el mercado se usa su cuota sin margen.
    Si no, la media de las probabilidades sin margen de todas las casas (consenso).
    """
    per_market: dict[str, list[dict[str, float]]] = {}
    sharp: dict[str, dict[str, float]] = {}
    for book in event.get("bookmakers", []):
        for mid, prices in _book_markets(book).items():
            expected = 3 if mid == "h2h" else 2
            if len(prices) != expected:
                continue
            probs = devig(prices)
            per_market.setdefault(mid, []).append(probs)
            if book.get("key") == sharp_book:
                sharp[mid] = probs

    result = {}
    for mid, lst in per_market.items():
        if mid in sharp:
            result[mid] = {"probs": sharp[mid], "source": "pinnacle", "books": len(lst)}
        elif len(lst) >= 3:
            names = lst[0].keys()
            avg = {n: mean(p[n] for p in lst if n in p) for n in names}
            s = sum(avg.values())
            result[mid] = {"probs": {n: v / s for n, v in avg.items()}, "source": "consenso", "books": len(lst)}
    return result


def best_prices(event: dict, sharp_book: str) -> dict[str, dict[str, dict]]:
    """Mejor cuota disponible por resultado en casas 'blandas' (sin sharp ni exchanges)."""
    best: dict[str, dict[str, dict]] = {}
    for book in event.get("bookmakers", []):
        key = book.get("key")
        if key == sharp_book or key in EXCLUDED_BOOKS:
            continue
        for mid, prices in _book_markets(book).items():
            for name, price in prices.items():
                cur = best.setdefault(mid, {}).get(name)
                if cur is None or price > cur["price"]:
                    best[mid][name] = {"price": price, "book": book.get("title", key)}
    return best


def _pois(k: int, lam: float) -> float:
    return exp(-lam) * lam**k / factorial(k)


def poisson_probs(lam_home: float, lam_away: float, max_goals: int = 10) -> dict:
    """Probabilidades 1X2 y over/under 2.5 a partir de goles esperados."""
    home = draw = away = under25 = 0.0
    for h in range(max_goals + 1):
        ph = _pois(h, lam_home)
        for a in range(max_goals + 1):
            p = ph * _pois(a, lam_away)
            if h > a:
                home += p
            elif h == a:
                draw += p
            else:
                away += p
            if h + a <= 2:
                under25 += p
    tot = home + draw + away
    return {
        "home": home / tot,
        "draw": draw / tot,
        "away": away / tot,
        "under25": under25 / tot,
        "over25": 1 - under25 / tot,
    }


def kelly_stake(prob: float, odds: float, fraction: float) -> float:
    """Stake recomendado como % del bank (Kelly fraccionado)."""
    b = odds - 1
    if b <= 0:
        return 0.0
    k = (prob * b - (1 - prob)) / b
    return max(0.0, k * fraction) * 100
