"""Configuración leída de variables de entorno (se definen en Render → Environment)."""
import os
from dataclasses import dataclass, field


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# Ligas analizadas: clave en The Odds API + id en footballdata.io (verificados en /leagues).
# El plan gratuito de footballdata.io incluye: Premier (15), LaLiga (10), Champions (45),
# Europa League (46) y World Cup (50). Se activan con ENABLED_LEAGUES (por código).
ALL_LEAGUES = [
    {"code": "PL", "key": "soccer_epl", "name": "Premier League", "fdio_id": 15},
    {"code": "LALIGA", "key": "soccer_spain_la_liga", "name": "LaLiga", "fdio_id": 10},
    {"code": "UCL", "key": "soccer_uefa_champs_league", "name": "Champions League", "fdio_id": 45},
    {"code": "UEL", "key": "soccer_uefa_europa_league", "name": "Europa League", "fdio_id": 46},
]
_enabled = {c.strip().upper() for c in os.getenv("ENABLED_LEAGUES", "PL,LALIGA,UCL,UEL").split(",") if c.strip()}
LEAGUES = [lg for lg in ALL_LEAGUES if lg["code"] in _enabled]

# Casas que no se usan para apostar (exchanges con comisión)
EXCLUDED_BOOKS = {"betfair_ex_eu", "betfair_ex_uk", "matchbook", "smarkets"}


@dataclass
class Settings:
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    fdio_key: str = field(default_factory=lambda: os.getenv("FOOTBALLDATA_IO_KEY", ""))
    # Modelo de estadísticas
    xg_weight: float = field(default_factory=lambda: _f("XG_WEIGHT", 0.6))
    half_life_days: float = field(default_factory=lambda: _f("HALF_LIFE_DAYS", 75))
    prematch_weight: float = field(default_factory=lambda: _f("PREMATCH_XG_WEIGHT", 0.3))
    refresh_token: str = field(default_factory=lambda: os.getenv("REFRESH_TOKEN", ""))
    regions: str = field(default_factory=lambda: os.getenv("ODDS_REGIONS", "eu"))
    markets: str = field(default_factory=lambda: os.getenv("ODDS_MARKETS", "h2h,totals"))
    sharp_book: str = field(default_factory=lambda: os.getenv("SHARP_BOOK", "pinnacle"))
    cache_hours: float = field(default_factory=lambda: _f("CACHE_HOURS", 24))
    days_ahead: int = field(default_factory=lambda: _i("DAYS_AHEAD", 7))
    num_picks: int = field(default_factory=lambda: _i("NUM_PICKS", 10))
    min_edge: float = field(default_factory=lambda: _f("MIN_EDGE", 0.02))
    min_odds: float = field(default_factory=lambda: _f("MIN_ODDS", 1.5))
    max_odds: float = field(default_factory=lambda: _f("MAX_ODDS", 5.0))
    # Peso del mercado frente al modelo de estadísticas (0..1)
    market_weight: float = field(default_factory=lambda: _f("MARKET_WEIGHT", 0.7))
    kelly_fraction: float = field(default_factory=lambda: _f("KELLY_FRACTION", 0.25))
    demo_env: str = field(default_factory=lambda: os.getenv("DEMO_MODE", ""))
    # Analista IA (Google Antigravity vía Gemini API)
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    analyst_agent: str = field(default_factory=lambda: os.getenv("ANALYST_AGENT", "antigravity-preview-05-2026"))
    analyst_candidates: int = field(default_factory=lambda: _i("ANALYST_CANDIDATES", 15))
    analyst_max_adjust: float = field(default_factory=lambda: _f("ANALYST_MAX_ADJUST", 0.03))
    analyst_timeout: float = field(default_factory=lambda: _f("ANALYST_TIMEOUT", 900))
    analyst_env: str = field(default_factory=lambda: os.getenv("ANALYST_ENABLED", ""))

    @property
    def analyst(self) -> bool:
        """Activo si hay GEMINI_API_KEY (o en demo, simulado). ANALYST_ENABLED=0 lo apaga."""
        if self.analyst_env.lower() in ("0", "false", "no"):
            return False
        return bool(self.gemini_api_key) or self.demo

    @property
    def demo(self) -> bool:
        if self.demo_env.lower() in ("1", "true", "yes", "si"):
            return True
        if self.demo_env.lower() in ("0", "false", "no"):
            return False
        return not self.odds_api_key
