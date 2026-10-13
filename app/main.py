import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Paths are built from this file's location, so the app works from any
# working directory (locally and on Render).
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Reads .env if it exists; harmless if it doesn't, so the app starts without keys.
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Taste Passport")


@app.get("/api/health")
def health():
    # Only booleans are returned - never the key values themselves.
    return {
        "status": "ok",
        "app": "taste-passport",
        "version": "0.1.0",
        "qloo_key_configured": bool(os.getenv("QLOO_API_KEY")),
        "llm_key_configured": bool(os.getenv("LLM_API_KEY")),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
