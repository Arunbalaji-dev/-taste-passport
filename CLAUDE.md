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

**Implemented in `DIALS` (app/qloo.py), tuned on live Berlin, Tokyo, Toronto and Chennai data:** the dial is a popularity band (0-1 percentile). Comfort = popularity >= 0.85; Bridge = 0.5 to 0.85; Adventure = <= 0.5 plus signal.location.weight=high. In all four cities the three bands share zero places, and affinity stays about the same (0.67-0.87), so going further out does not make the taste match worse. Place types are limited by `DEFAULT_PLACE_TAGS` (restaurant, museum, park, live music venue).

Known limits (be honest about these in the UI and README): Qloo "place" data is loose, so Adventure can still include odd picks (a gym, a hotel, repeated chain names like Tim Hortons). Never hide or invent results to cover this; de-duplicate by name and let the explanation say what Qloo actually returned.

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
  tests/
    test_main.py
    test_qloo.py
```

## Build phases (work one at a time, commit after each works)

0. Setup: repo, MIT license, this file, `.env.example`, keys (DONE)
1. Walking skeleton: "Hello Taste Passport" page served by FastAPI, deployed live (DONE)
2. Qloo tools: `search_entities`, `find_places(city, entity_ids, dial, tags)`, `find_local_culture(city, entity_ids, culture_type)` (DONE; see "Confirmed from live data")
3. Agent loop + Adventure Dial logic + grounding checks (DONE: app/agent.py, POST /api/passport, personalization test; see "Groq / LLM notes")
4. Real website: input form, dial slider, result cards, map, loading and error states, mobile layout
5. Hardening: cache Qloo responses, timeouts, retries, friendly fallbacks, cold-start message
6. Final deploy, README with run instructions, project description

## Chosen features (backlog, built inside the phases above)

All four use data already confirmed in "Confirmed from live data". Do not add other features until these work.

1. **"Why this fits you" bars (Phase 3 data, Phase 4 UI).** Each card shows how much each favourite contributed, e.g. "60% Interstellar, 40% A.R. Rahman", taken from `contributions` (Qloo explainability scores). The LLM may only describe these numbers, never invent them. If a result has no contributions, say so.
2. **Map with dial-coloured pins (Phase 4).** Leaflet + OpenStreetMap, using lat/lon from `find_places`. Pin colour = which dial setting (Comfort, Bridge, Adventure) the place came from. Places without lat/lon are listed but not pinned.
3. **Three-column dial view (Phase 4).** Comfort, Bridge and Adventure shown side by side for the same city and taste, so the difference is visible. Costs 3 Qloo calls per search, so cache them (Phase 5).
4. **Group Passport (Phase 3 logic, Phase 4 UI).** Two or more people each enter favourites; combine all their entity IDs into one taste list. For each place, show the per-person split from `contributions` (map each entity ID back to the person who entered it). Before claiming it works, test that two very different people give results that differ from either person alone.

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

## Confirmed from live data (Phase 2, real responses in raw/ and live calls)

- Search: GET /search?query=<name>&types=<urn:entity:type>&take=N returns results[] (a plain list, not results.entities) with name, entity_id, types (a LIST), popularity, disambiguation. Insights results use `type`/`subtype` (strings), not `types`.
- Place fields: name, entity_id, popularity (0-1), location.lat/lon, tags[] (id, name), properties.address / description / images[].url, query.affinity, query.explainability["signal.interests.entities"] = [{entity_id, score}] (in all samples seen, the scores add up to about 1 across the inputs). Affinity is absent when there is no taste input. Lists can contain null items, so always skip empties.
- Non-place fields (artist, brand, tv_show, podcast): same shape, but the image is properties.image.url (one dict) and there is no location, address or lat/lon.
- filter.tags: a comma-separated list means OR; a repeated parameter returns 400; a parent tag also matches its children (restaurant includes bar, cafe, bakery).
- **filter.location.query is silently IGNORED for artist, brand, tv_show, podcast, movie, person and book** (Berlin and Tokyo returned identical lists). Use signal.location.query instead for these; it does change the results (different brands per city, a Berlin-set show for Berlin). Only place and destination respect filter.location. Treat the results as "what Qloo ranks higher for this city and taste", never as "this artist is from this city".
- video_game returns 400 with a location. destination returns neighbourhoods/cities (2-4 results), not venues.
- **Personalization is uneven (tested Phase 3).** Taste A (Interstellar + A.R. Rahman) vs taste B (Metallica + Fast & Furious), 15 results each, shared places: Tokyo 2-4, Toronto 1-4 (good), but Berlin 9 and Chennai 7-11 (weak, nearly the same list). Changing signal.interests.entities.weight, signal.location.weight or sort_by made NO difference, so this is a Qloo data limit, not something we can tune. Do not claim "personalized for you" without qualification. DECISION (owner): the UI does NOT show a per-city "results look generic" warning; the limitation is instead stated once in the README. Keep marketing copy modest (say "based on your taste", not "uniquely personalized").
- The per-place "fits" shares are close to even (about 40/60 to 60/40) for every place, so the "why this fits you" bars show which favourites contributed, but they do not rank places against each other. Do not present them as a strong signal.
- Group Passport (A+B combined) vs A alone shares 10-14 of 15 in Berlin and Chennai, but only 3-10 in Tokyo and Toronto. Combining tastes visibly changes results only in cities where Qloo is taste-sensitive.

- **Place photos are unreliable.** Many place image URLs (images.qloo.com/...-420x-outside.jpg) return 504 from Qloo's image server (checked in Tokyo: 8 of 8 failed; artist/brand photos ending in -420x-auto.jpg load fine). The UI therefore always renders a letter tile under the photo and hides the photo if it fails. Never depend on a place photo being there.

## Groq / LLM notes (confirmed Phase 3)

- Provider: Groq (OpenAI-compatible, https://api.groq.com/openai/v1/chat/completions). Models available to our key include openai/gpt-oss-120b (default, set with LLM_MODEL), openai/gpt-oss-20b (backup), qwen/qwen3.8-27b.
- Free-tier limit: **8,000 tokens per minute PER MODEL**, about 1,000 requests per day. One passport run costs roughly 5-7k tokens, so expect about one passport per minute per model. `llm_call` falls back to the backup model on a 429, then waits up to 20 seconds once, then shows a friendly message. The three-column dial view (3 runs) must therefore share one LLM call or use cached results; never run three agent loops at once.
- gpt-oss models "think" before answering; reasoning_effort="low" keeps this cheap. With a tiny max_tokens the visible answer can come back empty, so never set max_tokens low.
- Grounding design: the LLM only picks tools and writes one short note per pick. All card data comes from Qloo results keyed by entity_id; picks with an unknown entity_id are dropped, duplicate names are removed, and if the LLM output is unusable we show Qloo's own top results without notes. Checked live: facts in the notes came from Qloo descriptions, not from LLM knowledge.
