# Picks con valor

Web que analiza cuotas y estadísticas de las 5 grandes ligas y muestra cada semana las 10 apuestas con más valor esperado.

## Cómo funciona

1. **Cuotas** de [The Odds API](https://the-odds-api.com) (1X2 y más/menos goles, región `eu`).
2. **Probabilidad de mercado**: cuota de Pinnacle sin margen. Si Pinnacle no cotiza, usa el consenso de todas las casas.
3. **Modelo de estadísticas** con [API-Football](https://www.api-football.com): goles a favor y en contra en casa y fuera, más un ajuste por la forma de los últimos 5 partidos. Con eso calcula goles esperados y aplica Poisson.
4. **Probabilidad final** = `MARKET_WEIGHT × mercado + (1 − MARKET_WEIGHT) × modelo`.
5. **Valor** = probabilidad × mejor cuota en casas blandas − 1. Se queda con una selección por partido y el top 10.
6. **Stake** = Kelly × `KELLY_FRACTION` (¼ por defecto), en % del bank.

7. **Analista IA (Google Antigravity)**: los 15 mejores candidatos se envían al agente de Antigravity (Gemini API, Interactions API). El agente busca en Google bajas, rotaciones, motivación y noticias, y devuelve un veredicto por pick (mantener / reducir stake / descartar), un ajuste de probabilidad limitado a ±3 puntos y el motivo con sus fuentes. Se ejecuta en segundo plano: la página muestra primero los picks sin revisar y se actualiza sola cuando el análisis termina, que puede tardar varios minutos. Si el agente falla, se quedan los picks sin revisar y se muestra el aviso.

Los resultados se guardan en caché `CACHE_HOURS` horas (24 por defecto), así que cada actualización gasta unos 10 créditos de The Odds API (5 ligas × 2 mercados) y 5 peticiones de API-Football. Con los planes gratuitos te llega.

Sin `ODDS_API_KEY` la web arranca en **modo demo** con datos ficticios.

Si API-Football falla (por ejemplo, porque el plan gratuito no da la temporada actual), la web sigue funcionando solo con el mercado y lo indica en los avisos.

## Desplegar en Render

1. Sube esta carpeta a un repositorio de GitHub.
2. En Render: **New → Blueprint** y elige el repo. Detecta `render.yaml` y crea el servicio web.
3. Rellena las variables que pide:
   - `ODDS_API_KEY` → regístrate en the-odds-api.com
   - `API_FOOTBALL_KEY` → dashboard.api-football.com (no la de RapidAPI)
   - `GEMINI_API_KEY` → aistudio.google.com → *Get API key*. Activa el analista de Antigravity. Sin ella, el analista no se ejecuta (en modo demo se simula).
   - `REFRESH_TOKEN` se genera solo. Lo ves en *Environment* y sirve para el botón "Forzar actualización".
4. Despliega y abre la URL.

También puedes crearlo a mano con **New → Web Service**:
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

> En el plan gratuito, Render duerme el servicio tras 15 min sin visitas. La primera carga tarda unos segundos y, si la caché se perdió, regenera los picks (gastando créditos). Si quieres evitarlo, usa el plan Starter o reduce las visitas de "despertar".

## Local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
DEMO_MODE=1 uvicorn app.main:app --reload   # http://localhost:8000
pytest -q
```

## Variables de configuración

| Variable | Defecto | Qué hace |
|---|---|---|
| `NUM_PICKS` | 10 | Número máximo de picks |
| `MIN_EDGE` | 0.02 | Valor mínimo (2 %) |
| `MIN_ODDS` / `MAX_ODDS` | 1.5 / 5.0 | Rango de cuotas |
| `MARKET_WEIGHT` | 0.7 | 1 = solo mercado, 0 = solo modelo |
| `KELLY_FRACTION` | 0.25 | Fracción de Kelly para el stake |
| `DAYS_AHEAD` | 7 | Ventana de partidos |
| `CACHE_HOURS` | 24 | Cada cuánto se regeneran los picks |
| `SHARP_BOOK` | pinnacle | Casa de referencia |
| `ANALYST_ENABLED` | auto | `0` apaga el analista aunque haya clave |
| `ANALYST_CANDIDATES` | 15 | Candidatos que revisa el agente |
| `ANALYST_MAX_ADJUST` | 0.03 | Ajuste máximo de probabilidad que puede aplicar |
| `ANALYST_TIMEOUT` | 900 | Segundos máximos de espera al agente |
| `ANALYST_AGENT` | antigravity-preview-05-2026 | Id del agente (cámbialo si Google saca una versión nueva) |

Las ligas se cambian en `app/config.py` (`LEAGUES`).

## Estructura

```
app/
  main.py       rutas: /, /api/picks, /api/refresh, /health
  picks.py      orquestación, ranking y caché
  model.py      quitar margen, Poisson, valor, Kelly
  odds.py       cliente The Odds API
  stats.py      cliente API-Football, ratings y emparejado de nombres
  analyst.py    analista IA con el agente de Google Antigravity
  demo_data.py  datos ficticios
static/         página (HTML/CSS/JS)
tests/
render.yaml     blueprint de Render
```

## Próximos pasos recomendados

- **Histórico y CLV**: guardar cada pick en una base de datos (Render Postgres o Supabase) junto con la cuota de cierre y el resultado. Es la única forma de saber si el modelo gana de verdad.
- **Backtest** del modelo con los CSV de football-data.co.uk antes de subir `1 − MARKET_WEIGHT`.
- **Mejor modelo**: Dixon-Coles o xG en lugar de goles reales.

Aviso: el valor es una estimación, no una garantía. Juega con responsabilidad. +18.
