import hashlib

from fastapi.testclient import TestClient

from app import main


def test_refresh_token_trimmed_and_health(monkeypatch):
    monkeypatch.setenv("REFRESH_TOKEN", "  secreto-x \n")
    monkeypatch.setattr(main, "get_picks", lambda s, force=False: {"ok": True})
    c = TestClient(main.app)
    h = c.get("/health").json()
    assert h["refresh_token_configured"] is True
    assert h["refresh_token_fingerprint"] == hashlib.sha256(b"secreto-x").hexdigest()[:6]
    assert c.post("/api/refresh", headers={"X-Refresh-Token": " secreto-x "}).status_code == 200
    r = c.post("/api/refresh", headers={"X-Refresh-Token": "otro"})
    assert r.status_code == 401
    d = r.json()["detail"]
    assert d["received_length"] == 4 and d["received_fingerprint"] == hashlib.sha256(b"otro").hexdigest()[:6]
    assert "otro" not in r.text


def test_refresh_without_token_configured(monkeypatch):
    monkeypatch.delenv("REFRESH_TOKEN", raising=False)
    c = TestClient(main.app)
    assert c.get("/health").json()["refresh_token_configured"] is False
    assert c.post("/api/refresh", headers={"X-Refresh-Token": "x"}).status_code == 401
