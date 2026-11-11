# Picks con valor

Web que analiza cuotas y estadísticas (con xG) de Premier League, LaLiga, Champions y Europa League y muestra cada semana las 10 apuestas con más valor esperado.

## Cómo funciona

1. **Cuotas** de [The Odds API](https://the-odds-api.com) (1X2 y más/menos goles, región `eu`, varias casas).
2. **Probabilidad de mercado**: cuota de Pinnacle sin margen. Si Pinnacle no cotiza, usa el consenso de todas las casas.
3. **Modelo de estadísticas** con [footballdata.io](https://footballdata.io):
   - Ataque y defensa de cada equipo **en casa y fuera**, a partir de los partidos jugados de la temporada actual.
   - Cada partido cuenta como `XG_WEIGHT × xG + (1 − XG_WEIGHT) × goles` (0,6 por defecto). Si un partido no tiene xG, se usan los goles reales.
   - Los partidos recientes pesan más (semivida `HALF_LIFE_DAYS`, 75 días).
   - Ajuste suave por la forma de los últimos 5 partidos (±7 % como máximo).
   - Los goles esperados resultantes se mezclan con el **xG prepartido** que publica footballdata.io (`PREMATCH_XG_WEIGHT`, 0,3) y se aplica Poisson.
4. **Probabilidad final** = `MARKET_WEIGHT × mercado + (1 − MARKET_WEIGHT) × modelo`.
5. **Valor** = probabilidad × mejor cuota en casas blandas − 1. Se queda con una selección por partido y el top 10.
6. **Stake** = Kelly × `KELLY_FRACTION` (¼ por defecto), en % del bank.
7. **Analista IA (Google Antigravity)**: los 15 mejores candidatos se envían al agente de Antigravity (Gemini API, Interactions API). El agente busca bajas, rotaciones, motivación y noticias, y devuelve un veredicto por pick (mantener / reducir stake / descartar), un ajuste de probabilidad limitado a ±3 puntos y el motivo con sus fuentes. Va en segundo plano y la página se actualiza sola al terminar.

### Lo que se ha comprobado de footballdata.io (con respuestas reales, plan gratuito)

- Ligas incluidas en el plan gratuito: Premier (15), LaLiga (10), Champions (45), Europa League (46) y World Cup (50). Límite: **1.000 peticiones al mes**.
- `/leagues/{id}/standings` da la temporada actual y la clasificación, pero **los campos home/away vienen a 0**. Por eso el split casa/fuera se calcula a partir de los partidos.
- `/matches` trae marcador, xG real y xG prepartido. Las fechas (`date_unix`) están en UTC.
- `/matches/{id}/odds` viene **todo a 0** en el plan gratuito. Por eso las cuotas siguen saliendo de The Odds API.
- El plan gratuito exige atribución: la página enlaza a footballdata.io.

Las respuestas reales están guardadas en `tests/fixtures/` y los tests trabajan sobre ellas.

### Consumo por actualización

| API | Por actualización | Límite gratuito |
|---|---|---|
| The Odds API | ~8 créditos (4 ligas × 2 mercados) | 500/mes |
| footballdata.io | ~3-4 peticiones por liga, unas 14 en total | 1.000/mes |

Con `CACHE_HOURS=24` son unas 30 actualizaciones al mes, dentro de los dos límites.

> **Ojo con Render gratis:** el servicio se duerme tras 15 min sin visitas y al despertar pierde la caché, que está en `/tmp`. Cada despertar puede volver a generar los picks y gastar peticiones. Si las visitas son frecuentes, sube `CACHE_HOURS`, usa el plan Starter con disco persistente o guarda la caché en una base de datos externa.

Sin `ODDS_API_KEY` la web arranca en **modo demo** con datos ficticios.

## Desplegar en Render

1. Sube esta carpeta a un repositorio de GitHub.
2. En Render: **New → Blueprint** y elige el repo. Detecta `render.yaml`.
3. Rellena las variables en **Environment**:
   - `ODDS_API_KEY` → the-odds-api.com. **Obligatoria**: es la única fuente de cuotas.
   - `FOOTBALLDATA_IO_KEY` → footballdata.io/signup. Activa el modelo de estadísticas.
   - `GEMINI_API_KEY` → aistudio.google.com. Activa el analista de Antigravity.
   - `REFRESH_TOKEN` se genera solo y sirve para el botón "Forzar actualización".
4. **Save, rebuild, and deploy**.

A mano (**New → Web Service**):
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

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
| `ENABLED_LEAGUES` | PL,LALIGA,UCL,UEL | Ligas activas |
| `NUM_PICKS` | 10 | Número máximo de picks |
| `MIN_EDGE` | 0.02 | Valor mínimo (2 %) |
| `MIN_ODDS` / `MAX_ODDS` | 1.5 / 5.0 | Rango de cuotas |
| `MARKET_WEIGHT` | 0.7 | 1 = solo mercado, 0 = solo modelo |
| `XG_WEIGHT` | 0.6 | Peso del xG frente a los goles reales |
| `HALF_LIFE_DAYS` | 75 | Semivida del peso de los partidos (dinámica) |
| `PREMATCH_XG_WEIGHT` | 0.3 | Mezcla con el xG prepartido de footballdata.io (0 lo desactiva) |
| `KELLY_FRACTION` | 0.25 | Fracción de Kelly para el stake |
| `DAYS_AHEAD` | 7 | Ventana de partidos |
| `CACHE_HOURS` | 24 | Cada cuánto se regeneran los picks |
| `SHARP_BOOK` | pinnacle | Casa de referencia |
| `ANALYST_ENABLED` | auto | `0` apaga el analista aunque haya clave |
| `ANALYST_CANDIDATES` | 15 | Candidatos que revisa el agente |
| `ANALYST_MAX_ADJUST` | 0.03 | Ajuste máximo de probabilidad del agente |
| `ANALYST_TIMEOUT` | 900 | Segundos máximos de espera al agente |
| `ANALYST_AGENT` | antigravity-preview-05-2026 | Id del agente |

## Estructura

```
app/
  main.py       rutas: /, /api/picks, /api/refresh, /health
  picks.py      orquestación, ranking y caché
  model.py      quitar margen, Poisson, valor, Kelly
  odds.py       cliente The Odds API
  fdio.py       cliente footballdata.io y ratings con xG
  stats.py      emparejado de nombres entre APIs y goles esperados
  analyst.py    analista IA con el agente de Google Antigravity
  demo_data.py  datos ficticios
static/         página (HTML/CSS/JS)
tests/          tests (+ fixtures con respuestas reales de footballdata.io)
render.yaml     blueprint de Render
```

## Próximos pasos recomendados

- **Histórico y CLV**: guardar cada pick con su cuota de cierre y su resultado en una base de datos. Es la única forma de saber si el modelo gana de verdad.
- **Backtest** con temporadas anteriores (footballdata.io tiene histórico desde 2007, aunque el xG de las temporadas antiguas viene a 0) antes de bajar `MARKET_WEIGHT`.

Aviso: el valor es una estimación, no una garantía. Juega con responsabilidad. +18.
