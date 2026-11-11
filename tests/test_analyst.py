import sys
import time
import types

from app import analyst, picks
from app.config import Settings


def _pick(edge=0.08, odds=2.5, prob=0.432):
    return {"league": "LaLiga", "home": "A", "away": "B", "kickoff": "2026-11-14T15:00:00Z",
            "selection": "Gana A", "odds": odds, "bookmaker": "X", "prob": prob,
            "prob_market": prob, "prob_model": None, "edge": edge, "fair_odds": 2.3, "stake_pct": 1.0}


def test_parse_verdicts_with_fence_and_text():
    text = 'Aquí va:\n```json\n[{"id":"c1","verdict":"mantener","prob_adjust":0}]\n```\nFin'
    assert analyst.parse_verdicts(text)[0]["id"] == "c1"
    assert analyst.parse_verdicts('[{"id":"c1"}]')[0]["id"] == "c1"


def test_apply_verdicts_clamps_and_discards():
    s = Settings(odds_api_key="x", gemini_api_key="k")
    ps = [_pick(), _pick(edge=0.05), _pick(edge=0.04)]
    verdicts = [
        {"id": "c1", "verdict": "mantener", "prob_adjust": 0.5, "reason": "ok", "sources": ["https://a.com", "x"]},
        {"id": "c2", "verdict": "descartar", "prob_adjust": -0.03, "reason": "baja"},
        {"id": "c3", "verdict": "reducir", "prob_adjust": "raro", "reason": "duda"},
    ]
    kept, discarded = analyst.apply_verdicts(ps, verdicts, s)
    assert kept[0]["analysis"]["prob_adjust"] == 0.03  # tope aplicado
    assert kept[0]["analysis"]["sources"] == ["https://a.com"]
    assert len(discarded) == 1 and discarded[0]["analysis"]["verdict"] == "descartar"
    reduced = [p for p in kept if p["analysis"]["verdict"] == "reducir"][0]
    assert reduced["stake_pct"] < 1.0


def test_antigravity_flow_mocked(monkeypatch):
    """Simula la API de Interactions: background + polling hasta 'completed'."""
    calls = {"get": 0}

    class Inter:
        def __init__(self, status, text=None):
            self.id, self.status, self.output_text, self.errors = "int-1", status, text, None

    class Interactions:
        def create(self, **kw):
            assert kw["agent"] == "antigravity-preview-05-2026" and kw["background"] is True
            assert "Candidatos" in kw["input"]
            return Inter("in_progress")

        def get(self, _id):
            calls["get"] += 1
            return Inter("completed", '```json\n[{"id":"c1","verdict":"mantener","prob_adjust":0.01,"reason":"Sin bajas."}]\n```')

    class Client:
        def __init__(self, api_key):
            assert api_key == "k"
            self.interactions = Interactions()

    fake = types.ModuleType("google.genai")
    fake.Client = Client
    monkeypatch.setitem(sys.modules, "google.genai", fake)
    import google
    monkeypatch.setattr(google, "genai", fake, raising=False)
    monkeypatch.setattr(analyst.time, "sleep", lambda _: None)

    s = Settings(odds_api_key="x", gemini_api_key="k")
    kept, discarded, source = analyst.analyse([_pick()], s, "2026-11-10")
    assert source == "antigravity" and calls["get"] == 1
    assert kept[0]["analysis"]["reason"] == "Sin bajas." and kept[0]["prob"] == 0.442


def test_background_analysis_updates_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(picks, "CACHE_FILE", tmp_path / "c.json")
    monkeypatch.setattr(picks, "_cache", None)
    s = Settings(odds_api_key="", demo_env="1", max_odds=5.0, min_prob=0.0, max_model_gap=1.0, analyst_demo_delay=0)
    first = picks.get_picks(s, force=True)
    assert first["analysis"]["status"] == "pending" and "pool" not in first
    for _ in range(50):
        data = picks.get_picks(s)
        if data["analysis"]["status"] != "pending":
            break
        time.sleep(0.05)
    a = data["analysis"]
    assert (a["status"], a["source"], a["error"]) == ("done", "simulado", None)
    assert a["progress"]["done"] == a["progress"]["total"] > 0
    assert all("analysis" in p for p in data["picks"])
    assert len(data["picks"]) <= 10


def test_progress_by_batches_and_partial_failure(monkeypatch):
    s = Settings(odds_api_key="x", gemini_api_key="k", analyst_batch_size=2, analyst_concurrency=1)
    ps = [_pick(edge=0.08 - i * 0.001) for i in range(5)]  # 5 picks -> lotes de 2, 2, 1

    def fake_batch(batch, s_, today):
        if batch[0]["id"] == "c3":
            raise RuntimeError("timeout")
        return [{"id": c["id"], "verdict": "mantener", "prob_adjust": 0, "reason": "ok"} for c in batch]

    monkeypatch.setattr(analyst, "_analyse_batch", fake_batch)
    seen = []
    kept, discarded, source = analyst.analyse(ps, s, "2026-11-11", progress=lambda d, t, e: seen.append((d, t, len(e))))
    assert seen == [(0, 5, 0), (2, 5, 0), (4, 5, 1), (5, 5, 1)]
    verdicts = sorted(p["analysis"]["verdict"] for p in kept)
    assert verdicts.count("sin análisis") == 2 and verdicts.count("mantener") == 3


def test_all_batches_failed_raises(monkeypatch):
    s = Settings(odds_api_key="x", gemini_api_key="k", analyst_batch_size=2)
    monkeypatch.setattr(analyst, "_analyse_batch", lambda b, s_, t: (_ for _ in ()).throw(RuntimeError("caído")))
    try:
        analyst.analyse([_pick(), _pick()], s, "2026-11-11")
        assert False
    except RuntimeError as e:
        assert "caído" in str(e)
