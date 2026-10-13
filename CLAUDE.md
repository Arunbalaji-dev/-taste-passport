# Taste Passport

An agent-powered web app that helps people discover NEW places in any city that they will actually love, based on what they already love (music, film, food, brands). Built for the Qloo LLM Hackathon.

One-line pitch: "Discover new places in any city that you'll actually love, based on what you already love."

## Hard rules (never break these)

1. **Qloo is the source of truth.** The LLM must NEVER invent or recommend a place, venue, brand, or event that did not come from a Qloo API result. The LLM only (a) understands the user's input, (b) decides which Qloo tools to call, (c) explains Qloo results.
2. **Every explanation must be grounded.** "Why this fits you" text may only use facts present in the Qloo response (names, affinity, popularity, tags, location). If Qloo returns too little, say so honestly. Never fill gaps with guesses.
3. **Validate before showing.** After the agent answers, check that every place name shown to the user exists in the Qloo results for that request. Drop anything that does not.
4. **API keys stay on the server.** Never put the Qloo key or LLM key in frontend code, the repo, or logs. Load from environment variables. Keep `.env` in `.gitignore`; commit `.env.example` only.
5. **Free tools only.** No paid services. If a free tier is rate-limited, add caching and graceful fallbacks, not paid upgrades.
6. **Must be deployable.** The app must run as one hosted web app. Anything that only works on localhost does not count.

## Core feature: the Adventure Dial

The user picks how far from their comfort zone to go:
- **Comfort**: places close to what they already love
- **Bridge**: new experiences connected to their taste
- **Adventure**: distinctly local experiences (loved in this city specifically) that still fit their taste

Exact logic depends on which scores Qloo returns (affinity, popularity). Decide in Phase 2 by inspecting real responses. Do not guess the response shape; ask me to paste a real response first.

## Architecture

One FastAPI app serves both the website and the API.

```
Browser -> FastAPI
            |- serves static/ (HTML, Tailwind CDN, vanilla JS, Leaflet map)
            |- POST /api/passport -> agent loop
                 |- LLM (free tier: Groq or Gemini) with tool calling
                 |- Qloo tools: search_entities, find_places, find_local_culture
```

Agent = one LLM + 2-3 tools + one plain tool-calling loop. No multi-agent frameworks.

## Stack

- Backend: Python, FastAPI, httpx or requests
- LLM: Groq or Gemini free tier (behind one small `llm_call()` function so it can be swapped in one line)
- Frontend: plain HTML + Tailwind (CDN) + vanilla JS
- Map: Leaflet + OpenStreetMap (no API key)
- Hosting: Render free tier or Hugging Face Spaces
- License: MIT

## Folder structure

```
taste-passport/
  CLAUDE.md
  LICENSE
  README.md
  requirements.txt
  .env.example
  app/
    main.py      FastAPI: serves site + /api routes
    qloo.py      Qloo tool functions (the only file that talks to Qloo)
    agent.py     LLM tool-calling loop
    prompts.py   system prompts
  static/
    index.html
    style.css
    app.js
```

## Build phases (work one at a time, commit after each works)

0. Setup: repo, MIT license, this file, `.env.example`, keys
1. Walking skeleton: "Hello Taste Passport" page served by FastAPI, deployed live
2. Qloo tools: `search_entities`, `find_places(city, taste, dial)`, `find_local_culture`
3. Agent loop + Adventure Dial logic + grounding checks
4. Real website: input form, dial slider, result cards, map, loading and error states, mobile layout
5. Hardening: cache Qloo responses, timeouts, retries, friendly fallbacks, cold-start message
6. Final deploy, README with run instructions, project description

## Working style

- Make small changes. One step at a time; run it; then move on.
- Before writing code that depends on Qloo's response format, ask me to paste a real raw response. Never guess field names.
- Save raw Qloo responses in `raw/` (gitignored) while developing, so we can inspect them.
- Write a simple test for each Qloo tool function and for the grounding check.
- Keep code simple and readable. I am a beginner-to-intermediate developer; explain non-obvious choices in a short comment.
- Handle errors visibly: timeouts, empty results, and rate limits must show a friendly message, never a blank page or crash.
- Do not add dependencies without saying why.

## Qloo API notes (confirmed from the hackathon developer guide)

- Base URL: https://hackathon.api.qloo.com (the hackathon key ONLY works here; staging and production URLs return 401)
- Auth header: X-Api-Key
- Main endpoint: GET /v2/insights. Always append a path; the bare base URL returns 404.
- NEVER use /recommendations or /recs. They are legacy and unsupported.
- filter.type is REQUIRED on every Insights request. Supported values: urn:entity:artist, book, brand, destination, movie, person, place, podcast, tv_show, video_game. Music = artist (not "music"). Food and drink places = place. An unsupported type returns 403.
- Invalid or unsupported parameters are SILENTLY IGNORED (no error). Empty or suspiciously generic results usually mean a wrong parameter for that filter.type. Check the Entity Type Parameter Guide before blaming the data.
- filter.tags and signal.interests.tags need valid tag IDs from GET /v2/tags, not freeform text. signal.demographics.audiences needs valid audience URNs.
- Hackathon data may not cover every entity or region. Try a broader query before concluding there is no data.
- Quotas are high. If we hit limits, ask in the Qloo Hackathon Discord #api-help. Keys stay active through judging and are deactivated after.
- Confirmed Insights parameters (from the Insights API Deep Dive):
  - City by name: filter.location.query=<city> (fuzzy, case-insensitive; matches a locality; returns 400 if none found; the match is echoed in query.locality.signal). filter.location.radius=0 means strict boundary; the default pads it. filter.location also accepts "lat,lon", a WKT POINT, or a locality UUID.
  - Taste input: signal.interests.entities = comma-separated entity IDs. Cross-domain works (artist/movie IDs can drive place results). Strength: signal.interests.entities.weight and signal.location.weight (very_low|low|mid|medium|high|very_high, or a number).
  - Adventure Dial levers (DRAFT, tune with real data): filter.popularity.min/max (0-1 percentile), the two weights above, bias.trends, bias.quality, sort_by (affinity|distance|rating|quality).
  - Grounded explanations: feature.explainability=true adds query.explainability to each result (which input entities contributed, scores 0-1). Build "why this fits you" from this, not from LLM guesses.
  - Card helpers: filter.exists=properties.image or properties.description, filter.price_level.min/max (1-4), filter.rating.min/max, filter.hours=<weekday>, take (max 50), page.
  - Tags: filter.tags and signal.interests.tags need IDs from GET /v2/tags (example: urn:tag:genre:place:restaurant:japanese).
  - Response shape: success, results.entities[] (array), results.duration.
- The OpenAPI block on the docs page lists the production server. Ignore it and always use the hackathon base URL.
- Still UNCONFIRMED (verify from docs or real responses before coding): the search endpoint path and params (name -> entity ID), and the exact field names inside each entity (affinity, popularity, address, coordinates, image).
