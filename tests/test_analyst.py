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
            assert kw["api_version"] == "v1beta"
            assert "Candidatos" in kw["input"]
            return Inter("in_progress")

        def get(self, _id, api_version=None):
            assert api_version == "v1beta"
            calls["get"] += 1
            return Inter("completed", '```json\n[{"id":"c1","verdict":"mantener","prob_adjust":0.01,"reason":"Sin bajas."}]\n```')

    class Client:
        def __init__(self, api_key, http_options=None):
            assert api_key == "k" and http_options == {"api_version": "v1beta"}
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

    def fake_batch(batch, s_, today, should_stop=None):
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
    monkeypatch.setattr(analyst, "_analyse_batch", lambda b, s_, t, should_stop=None: (_ for _ in ()).throw(RuntimeError("caído")))
    try:
        analyst.analyse([_pick(), _pick()], s, "2026-11-11")
        assert False
    except RuntimeError as e:
        assert "caído" in str(e)


def test_real_sdk_routes_interactions_to_v1beta():
    """Con la librería real: el cliente creado como en analyst.py apunta a v1beta (por defecto sería v1)."""
    from google import genai
    from google.genai._gaos.google_genai import get_google_genai_api_version
    default = genai.Client(api_key="x")
    fixed = genai.Client(api_key="x", http_options={"api_version": "v1beta"})
    assert get_google_genai_api_version(default._api_client) == "v1"
    assert get_google_genai_api_version(fixed._api_client) == "v1beta"


def test_force_refresh_does_not_wait_for_old_analysis(monkeypatch, tmp_path):
    """Reproduce el fallo: análisis viejo colgado + forzar actualización -> el nuevo debe arrancar ya."""
    import threading as th
    monkeypatch.setattr(picks, "CACHE_FILE", tmp_path / "c.json")
    monkeypatch.setattr(picks, "_cache", None)
    monkeypatch.setattr(picks, "_analysis_running_for", None)
    release_old = th.Event()
    calls = []

    def fake_batch(batch, s_, today, should_stop=None):
        calls.append(today)
        if len(calls) == 1:  # el primer análisis se "cuelga" hasta que lo cancelan
            while not should_stop():
                time.sleep(0.01)
            release_old.set()
            raise analyst.Cancelled()
        return [{"id": c["id"], "verdict": "mantener", "prob_adjust": 0, "reason": "nuevo"} for c in batch]

    monkeypatch.setattr(analyst, "_analyse_batch", fake_batch)
    s = Settings(odds_api_key="", demo_env="1", max_odds=5.0, min_prob=0.0, max_model_gap=1.0,
                 analyst_batch_size=50, analyst_concurrency=1)
    picks.get_picks(s, force=True)           # arranca el análisis 1 (se cuelga)
    time.sleep(0.05)
    time.sleep(0.01)
    second = picks.get_picks(s, force=True)  # forzar actualización: nuevos picks
    assert release_old.wait(2), "el análisis viejo debía cancelarse"
    for _ in range(100):
        data = picks.get_picks(s)
        if data["analysis"]["status"] == "done":
            break
        time.sleep(0.02)
    assert data["generated_at"] == second["generated_at"]
    assert data["analysis"]["status"] == "done"
    assert all(p["analysis"]["reason"] == "nuevo" for p in data["picks"])


def _fake_genai(monkeypatch, script):
    """script: lista de estados que irá devolviendo la API (create y get)."""
    import google
    created = []

    class Inter:
        def __init__(self, status, iid, token=None, text=None):
            self.id, self.status, self.continuation_token, self.output_text, self.errors = iid, status, token, text, None

    class Interactions:
        def create(self, **kw):
            created.append(kw)
            return script.pop(0)

        def get(self, _id, api_version=None):
            return script.pop(0)

        def cancel(self, _id, api_version=None):
            created.append({"cancel": _id})

    class Client:
        def __init__(self, api_key, http_options=None):
            self.interactions = Interactions()

    fake = types.ModuleType("google.genai")
    fake.Client = Client
    monkeypatch.setitem(sys.modules, "google.genai", fake)
    monkeypatch.setattr(google, "genai", fake, raising=False)
    monkeypatch.setattr(analyst.time, "sleep", lambda _: None)
    return Inter, created


def test_requires_continuation_is_resumed(monkeypatch):
    script = []
    Inter, created = _fake_genai(monkeypatch, script)
    ok = '[{"id":"c1","verdict":"mantener","prob_adjust":0,"reason":"ok"}]'
    script += [Inter("in_progress", "i1"), Inter("requires_continuation", "i1", token="tok"),
               Inter("in_progress", "i2"), Inter("completed", "i2", text=ok)]
    s = Settings(odds_api_key="x", gemini_api_key="k")
    out = analyst._run_antigravity("prompt", s, label="c1")
    assert out == ok
    assert created[1]["continuation_token"] == "tok" and created[1]["previous_interaction_id"] == "i1"
    assert "input" not in created[1]


def test_timeout_reports_last_status(monkeypatch):
    script = []
    Inter, created = _fake_genai(monkeypatch, script)
    script += [Inter("queued", "i1")] + [Inter("queued", "i1") for _ in range(5)]
    s = Settings(odds_api_key="x", gemini_api_key="k", analyst_timeout=0)
    try:
        analyst._run_antigravity("prompt", s)
        assert False
    except TimeoutError as e:
        assert "último estado: queued" in str(e)
    assert {"cancel": "i1"} in created


def test_describe_steps_and_tokens():
    class St:
        def __init__(self, t, summary=None):
            self.type, self.summary = t, summary

    class U:
        total_tokens = 12345

    class It:
        steps = [St("thought"), St("google_search_call"), St("google_search_result"),
                 St("google_search_call"), St("thought", "Revisando bajas del Tottenham")]
        usage = U()

    d = analyst.describe(It())
    assert d.startswith("5 pasos") and "google_search_call=2" in d and "thought=2" in d
    assert "último=thought (Revisando bajas del Tottenham)" in d and "tokens=12345" in d
    assert analyst.describe(object()) == "0 pasos"


def test_agent_config_sent_only_when_set(monkeypatch):
    script = []
    Inter, created = _fake_genai(monkeypatch, script)
    ok = '[{"id":"c1","verdict":"mantener","prob_adjust":0,"reason":"ok"}]'
    script += [Inter("completed", "i1", text=ok), Inter("completed", "i2", text=ok)]
    analyst._run_antigravity("p", Settings(odds_api_key="x", gemini_api_key="k"))
    assert "agent_config" not in created[0]
    analyst._run_antigravity("p", Settings(odds_api_key="x", gemini_api_key="k", analyst_max_tokens=200000))
    assert created[1]["agent_config"] == {"type": "antigravity", "max_total_tokens": 200000}


def test_real_sdk_accepts_antigravity_agent_config():
    from google.genai._gaos.types.interactions.antigravityagentconfig import AntigravityAgentConfig
    cfg = AntigravityAgentConfig(**{"type": "antigravity", "max_total_tokens": 200000, "model": "x"})
    assert cfg.max_total_tokens == 200000
