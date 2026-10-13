import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
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

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines list every request URL
logger = logging.getLogger("taste-passport")

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


class Person(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    favourites: str = Field(min_length=2, max_length=300)


class ResolvedFavourite(BaseModel):
    entity_id: str = Field(max_length=64)
    name: str = Field(max_length=120)
    type: str | None = Field(default=None, max_length=60)
    person: str | None = Field(default=None, max_length=30)


class PassportRequest(BaseModel):
    # Length limits keep one request from sending huge text to the free-tier LLM.
    favourites: str = Field(default="", max_length=500)
    people: list[Person] | None = Field(default=None, max_length=4)  # Group Passport
    resolved: list[ResolvedFavourite] | None = Field(default=None, max_length=12)
    city: str = Field(min_length=2, max_length=80)
    dial: str = "bridge"


# Simple per-visitor limit so one person cannot use up the free AI quota for everyone.
RATE_LIMIT = 12  # requests ...
RATE_WINDOW_SECONDS = 60  # ... per minute, per visitor
_recent = defaultdict(deque)  # visitor -> times of recent requests
_recent_lock = threading.Lock()


def too_many_requests(visitor):
    now = time.time()
    with _recent_lock:
        times = _recent[visitor]
        while times and times[0] <= now - RATE_WINDOW_SECONDS:
            times.popleft()
        if len(times) >= RATE_LIMIT:
            return True
        times.append(now)
        if len(_recent) > 5000:  # keep memory small: forget visitors with no recent requests
            for key in [k for k, v in _recent.items() if not v]:
                del _recent[key]
        return False


def visitor_id(request: Request):
    # Behind Render's proxy the real address is the first X-Forwarded-For entry.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


@app.post("/api/passport")
def passport(request: PassportRequest, http_request: Request):
    if too_many_requests(visitor_id(http_request)):
        return JSONResponse(status_code=429, content={"error": "That's a lot of searches in a short time. Please wait a minute and try again."})
    if len(request.favourites.strip()) < 2 and not request.people:
        return JSONResponse(status_code=422, content={"error": "Tell me at least one thing you love."})
    try:
        return run_passport(
            request.favourites,
            request.city.strip(),
            request.dial,
            people=[p.model_dump() for p in request.people] if request.people else None,
            resolved=[r.model_dump() for r in request.resolved] if request.resolved else None,
        )
    except (AgentError, QlooError) as err:
        # Friendly message, never a stack trace or a blank page.
        return JSONResponse(status_code=502, content={"error": str(err)})
    except Exception:
        # A bug on our side. Log the type of problem (never request contents or keys).
        logger.exception("Unexpected error in /api/passport")
        return JSONResponse(status_code=500, content={"error": "Something went wrong on our side. Please try again in a moment."})


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
