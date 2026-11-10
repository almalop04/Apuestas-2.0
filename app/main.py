"""Servidor web: sirve la página y la API de picks."""
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


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/picks")
def picks():
    return get_picks(Settings())


@app.post("/api/refresh")
def refresh(x_refresh_token: str = Header(default="")):
    s = Settings()
    if not s.refresh_token or not hmac.compare_digest(x_refresh_token, s.refresh_token):
        raise HTTPException(status_code=401, detail="Token incorrecto")
    return get_picks(s, force=True)
