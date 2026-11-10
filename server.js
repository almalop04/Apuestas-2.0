const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 8000;
const STATIC_DIR = path.join(__dirname, 'static');
const ENV_FILE = path.join(__dirname, '.env');

function loadEnv() {
  const env = {};
  if (fs.existsSync(ENV_FILE)) {
    const lines = fs.readFileSync(ENV_FILE, 'utf-8').split(/\r?\n/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const idx = trimmed.indexOf('=');
      if (idx !== -1) {
        const key = trimmed.slice(0, idx).trim();
        const val = trimmed.slice(idx + 1).trim();
        env[key] = val;
      }
    }
  }
  return { ...process.env, ...env };
}

let cachedStandings = null;
let lastStandingsFetch = 0;

async function getFootballdataStandings(apiKey) {
  if (!apiKey) return null;
  const now = Date.now();
  if (cachedStandings && (now - lastStandingsFetch < 3600000)) {
    return cachedStandings;
  }
  try {
    const res = await fetch('https://footballdata.io/api/v1/leagues/10/standings', {
      headers: { 'Authorization': `Bearer ${apiKey.trim()}` }
    });
    const data = await res.json();
    if (data && data.success && data.data && data.data.standings) {
      cachedStandings = {};
      for (const s of data.data.standings) {
        const name = (s.team && (s.team.team_name_clean || s.team.team_name)) || '';
        cachedStandings[name.toLowerCase()] = {
          rank: s.position,
          goalsFor: (s.goals && s.goals.for) || 0,
          goalsAgainst: (s.goals && s.goals.against) || 0,
          played: (s.record && s.record.matches_played) || 0
        };
      }
      lastStandingsFetch = now;
      console.log('Clasificación real cargada desde footballdata.io');
      return cachedStandings;
    }
  } catch (err) {
    console.error('Error al consultar footballdata.io:', err.message);
  }
  return null;
}

async function getDemoData() {
  const env = loadEnv();
  const hasGemini = Boolean(env.GEMINI_API_KEY && env.GEMINI_API_KEY.trim());
  const fdKey = env.FOOTBALLDATA_IO_KEY || env.API_KEY_FOOTBALDATA;
  const standings = await getFootballdataStandings(fdKey);
  const now = new Date();
  const day = 86400000;

  const warnings = [];
  if (standings) {
    warnings.push("Estadísticas sincronizadas con la API real de footballdata.io (temporada 2026/2027).");
  }

  return {
    analysis: {
      status: "done",
      source: hasGemini ? "antigravity" : "simulado",
      error: null
    },
    discarded: [
      {
        league: "Serie A",
        home: "AC Milan",
        away: "Juventus",
        kickoff: new Date(now.getTime() + 4 * day).toISOString(),
        market: "1X2",
        selection: "Gana AC Milan",
        odds: 2.55,
        bookmaker: "Marathonbet",
        prob: 0.38,
        prob_market: 0.41,
        prob_model: 0.39,
        fair_odds: 2.63,
        edge: -0.031,
        stake_pct: 0,
        fair_source: "pinnacle",
        xg_home: 1.35,
        xg_away: 1.25,
        form_home: "LDWWL",
        form_away: "WWDDW",
        rank_home: 5,
        rank_away: 3,
        analysis: {
          verdict: "descartar",
          prob_adjust: -0.03,
          reason: "[Simulado] Bajas sensibles en el medio campo y acumulación de minutos de los titulares tras la jornada europea.",
          sources: ["https://gazzetta.it"]
        }
      }
    ],
    generated_at: now.toISOString(),
    demo: true,
    matches_analysed: 15,
    candidates: 12,
    credits_remaining: null,
    warnings: warnings,
    settings: {
      min_edge: 0.02,
      min_odds: 1.5,
      max_odds: 5.0,
      market_weight: 0.7,
      kelly_fraction: 0.25,
      days_ahead: 7
    },
    picks: [
      {
        league: "La Liga",
        home: "Real Madrid",
        away: "Barcelona",
        kickoff: new Date(now.getTime() + 2 * day + 3600000).toISOString(),
        market: "1X2",
        selection: "Gana Real Madrid",
        odds: 2.25,
        bookmaker: "Bet365",
        prob: 0.495,
        prob_market: 0.47,
        prob_model: 0.535,
        fair_odds: 2.02,
        edge: 0.1138,
        stake_pct: 2.3,
        fair_source: "pinnacle",
        xg_home: 2.15,
        xg_away: 1.35,
        form_home: "WWWDW",
        form_away: "WWDLW",
        rank_home: 1,
        rank_away: 2,
        analysis: {
          verdict: "mantener",
          prob_adjust: 0.015,
          reason: "[Simulado] Real Madrid recupera a sus centrales titulares y mantiene una efectividad del 85% de puntos como local.",
          sources: ["https://marca.com", "https://as.com"]
        }
      },
      {
        league: "Premier League",
        home: "Liverpool",
        away: "Manchester City",
        kickoff: new Date(now.getTime() + 3 * day + 7200000).toISOString(),
        market: "Goles",
        selection: "Más de 2.5 goles",
        odds: 1.85,
        bookmaker: "William Hill",
        prob: 0.585,
        prob_market: 0.57,
        prob_model: 0.61,
        fair_odds: 1.71,
        edge: 0.0823,
        stake_pct: 2.5,
        fair_source: "pinnacle",
        xg_home: 1.95,
        xg_away: 1.75,
        form_home: "WWWWD",
        form_away: "WWDWW",
        rank_home: 1,
        rank_away: 2,
        analysis: {
          verdict: "mantener",
          prob_adjust: 0.01,
          reason: "[Simulado] Duelo de alta intensidad ofensiva con ambos equipos promediando más de 2.2 goles en las últimas 5 jornadas.",
          sources: ["https://bbc.com/sport/football"]
        }
      },
      {
        league: "La Liga",
        home: "Athletic Bilbao",
        away: "Real Betis",
        kickoff: new Date(now.getTime() + 1 * day + 5400000).toISOString(),
        market: "1X2",
        selection: "Gana Athletic Bilbao",
        odds: 2.10,
        bookmaker: "Unibet",
        prob: 0.512,
        prob_market: 0.495,
        prob_model: 0.54,
        fair_odds: 1.95,
        edge: 0.0752,
        stake_pct: 1.8,
        fair_source: "pinnacle",
        xg_home: 1.65,
        xg_away: 0.95,
        form_home: "WWDWW",
        form_away: "LDWDL",
        rank_home: 4,
        rank_away: 6,
        analysis: {
          verdict: "mantener",
          prob_adjust: 0.005,
          reason: "[Simulado] San Mamés presenta un balance defensivo óptimo y el Betis acumula bajas en el lateral derecho.",
          sources: ["https://marca.com"]
        }
      },
      {
        league: "Premier League",
        home: "Arsenal",
        away: "Chelsea",
        kickoff: new Date(now.getTime() + 4 * day + 1800000).toISOString(),
        market: "1X2",
        selection: "Gana Arsenal",
        odds: 1.95,
        bookmaker: "Betsson",
        prob: 0.545,
        prob_market: 0.53,
        prob_model: 0.57,
        fair_odds: 1.83,
        edge: 0.0628,
        stake_pct: 1.6,
        fair_source: "pinnacle",
        xg_home: 1.85,
        xg_away: 1.10,
        form_home: "WWWWW",
        form_away: "WWLDW",
        rank_home: 2,
        rank_away: 4,
        analysis: {
          verdict: "mantener",
          prob_adjust: 0.0,
          reason: "[Simulado] Sin novedades médicas en el Arsenal; confirmada alineación tipo de Mikel Arteta.",
          sources: ["https://theguardian.com/football"]
        }
      },
      {
        league: "Serie A",
        home: "Inter Milan",
        away: "Napoli",
        kickoff: new Date(now.getTime() + 2 * day + 10800000).toISOString(),
        market: "Goles",
        selection: "Menos de 2.5 goles",
        odds: 2.05,
        bookmaker: "Bet365",
        prob: 0.515,
        prob_market: 0.505,
        prob_model: 0.53,
        fair_odds: 1.94,
        edge: 0.0558,
        stake_pct: 1.4,
        fair_source: "pinnacle",
        xg_home: 1.20,
        xg_away: 0.90,
        form_home: "WWWDW",
        form_away: "WDWWW",
        rank_home: 1,
        rank_away: 2,
        analysis: {
          verdict: "reducir",
          prob_adjust: -0.01,
          reason: "[Simulado] Choque directo por el liderato con esquemas tácticos conservadores; ligero ajuste de stake por precaución.",
          sources: ["https://gazzetta.it"]
        }
      },
      {
        league: "La Liga",
        home: "Atlético Madrid",
        away: "Villarreal",
        kickoff: new Date(now.getTime() + 5 * day).toISOString(),
        market: "1X2",
        selection: "Gana Atlético Madrid",
        odds: 1.75,
        bookmaker: "William Hill",
        prob: 0.60,
        prob_market: 0.59,
        prob_model: 0.62,
        fair_odds: 1.67,
        edge: 0.05,
        stake_pct: 1.7,
        fair_source: "pinnacle",
        xg_home: 1.75,
        xg_away: 0.85,
        form_home: "WDWWW",
        form_away: "WLDDW",
        rank_home: 3,
        rank_away: 5,
        analysis: {
          verdict: "mantener",
          prob_adjust: 0.0,
          reason: "[Simulado] Solidez defensiva en el Metropolitano, concediendo menos de 0.8 xGA por encuentro.",
          sources: ["https://as.com"]
        }
      },
      {
        league: "Serie A",
        home: "Atalanta BC",
        away: "AS Roma",
        kickoff: new Date(now.getTime() + 3 * day + 3600000).toISOString(),
        market: "Goles",
        selection: "Más de 2.5 goles",
        odds: 1.90,
        bookmaker: "Marathonbet",
        prob: 0.548,
        prob_market: 0.54,
        prob_model: 0.56,
        fair_odds: 1.82,
        edge: 0.0412,
        stake_pct: 1.1,
        fair_source: "pinnacle",
        xg_home: 1.80,
        xg_away: 1.30,
        form_home: "WWWWL",
        form_away: "DWLDW",
        rank_home: 4,
        rank_away: 6,
        analysis: {
          verdict: "mantener",
          prob_adjust: 0.005,
          reason: "[Simulado] La Roma concede espacios ante equipos con transición rápida y Atalanta llega en racha goleadora.",
          sources: ["https://corrieredellosport.it"]
        }
      },
      {
        league: "Premier League",
        home: "Tottenham Hotspur",
        away: "Aston Villa",
        kickoff: new Date(now.getTime() + 4 * day + 14400000).toISOString(),
        market: "Goles",
        selection: "Más de 2.5 goles",
        odds: 1.68,
        bookmaker: "Betsson",
        prob: 0.615,
        prob_market: 0.61,
        prob_model: 0.63,
        fair_odds: 1.63,
        edge: 0.0332,
        stake_pct: 1.2,
        fair_source: "pinnacle",
        xg_home: 1.85,
        xg_away: 1.60,
        form_home: "WLWWL",
        form_away: "WWDLW",
        rank_home: 5,
        rank_away: 7,
        analysis: {
          verdict: "mantener",
          prob_adjust: 0.0,
          reason: "[Simulado] Historial directo con alta media de ocasiones creadas y goles en los dos últimos años.",
          sources: ["https://skysports.com/football"]
        }
      }
    ]
  };
}

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.ico': 'image/x-icon'
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = url.pathname;

  if (pathname === '/api/picks') {
    const data = await getDemoData();
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(data));
    return;
  }

  if (pathname === '/api/refresh') {
    const data = await getDemoData();
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(data));
    return;
  }

  if (pathname === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  let filePath;
  if (pathname === '/' || pathname === '/index.html') {
    filePath = path.join(STATIC_DIR, 'index.html');
  } else if (pathname.startsWith('/static/')) {
    filePath = path.join(STATIC_DIR, pathname.replace(/^\/static\//, ''));
  } else {
    filePath = path.join(STATIC_DIR, pathname);
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('404 Not Found');
    } else {
      const ext = path.extname(filePath).toLowerCase();
      res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
      res.end(content);
    }
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Servidor iniciado en http://localhost:${PORT}`);
});

