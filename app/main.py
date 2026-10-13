import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import AgentError, run_passport
from app.qloo import QlooError

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


class PassportRequest(BaseModel):
    # Length limits keep one request from sending huge text to the free-tier LLM.
    favourites: str = Field(min_length=2, max_length=500)
    city: str = Field(min_length=2, max_length=80)
    dial: str = "bridge"


@app.post("/api/passport")
def passport(request: PassportRequest):
    try:
        return run_passport(request.favourites, request.city.strip(), request.dial)
    except (AgentError, QlooError) as err:
        # Friendly message, never a stack trace or a blank page.
        return JSONResponse(status_code=502, content={"error": str(err)})


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
