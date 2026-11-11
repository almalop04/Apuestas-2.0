"""Servidor web: sirve la página y la API de picks."""
import hashlib
import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .picks import get_picks

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Apuestas con valor", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:6]


@app.get("/health")
def health():
    """Diagnóstico sin exponer secretos: dice si hay token y su huella (6 caracteres de su SHA-256)."""
    token = Settings().refresh_token.strip()
    return {
        "ok": True,
        "refresh_token_configured": bool(token),
        "refresh_token_fingerprint": _fingerprint(token) if token else None,
    }


@app.get("/api/picks")
def picks():
    return get_picks(Settings())


@app.post("/api/refresh")
def refresh(x_refresh_token: str = Header(default="")):
    s = Settings()
    expected, given = s.refresh_token.strip(), x_refresh_token.strip()
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Token incorrecto")
    return get_picks(s, force=True)
