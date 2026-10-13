# Taste Passport

Discover new places in any city that you'll actually love, based on what you already love.

Taste Passport takes a few things you love (films, music, shows, brands), a city, and
how adventurous you feel, then asks [Qloo](https://www.qloo.com)'s taste data for places
and local culture that fit. Built for the Qloo LLM Hackathon.

## What it does

- **Adventure Dial.** Pick how far from your comfort zone to go:
  **Comfort** (well-known places close to your taste), **Bridge** (new places connected to
  your taste), or **Adventure** (lesser-known places that still fit). Each setting loads
  when you first choose it and is kept, so switching back is instant.
- **Why this fits you.** Every result shows how much each of your favourites contributed
  to the match, using Qloo's own scores.
- **Map.** Results appear on an OpenStreetMap map, with pins coloured by dial setting.
- **Group Passport.** Add up to four people, each with their own favourites, and see how
  much each person contributed to every match.
- **Local culture.** Artists Qloo ties to the city and your taste.

## How it works (and why you can trust the results)

```
Browser -> FastAPI -> one LLM (Groq) with tools -> Qloo API
```

The LLM never supplies a place. It only (1) understands what you typed, (2) decides which
Qloo tools to call, and (3) writes one short note per result. Everything on screen is
built from Qloo's response:

- Every pick the LLM makes must match an `entity_id` that Qloo actually returned. Any pick
  that does not is dropped before you see it.
- Notes may only use facts in the Qloo result (name, description, tags, scores).
- The Adventure Dial setting comes from you, never from the LLM.
- If the AI is unavailable, you still get Qloo's own results with Qloo's descriptions.
- API keys stay on the server and are never sent to the browser.

## Honest limits

- **Personalization varies by city.** In our tests two very different tastes got clearly
  different results in Tokyo and Toronto, but nearly the same list in Berlin and Chennai.
  That comes from Qloo's data for those cities, not from something we could tune.
- **The match bars are close to even** for most results. They show which favourites
  contributed, but they do not rank one place above another.
- **Place photos often fail to load.** Qloo's image server returns errors for many place
  photos, so cards fall back to a letter tile.
- **Culture results are "ranked higher for this city", not "from this city".**
- **Qloo's place data is loose.** Occasionally a gym or a hotel shows up. We show what
  Qloo returns and never hide or invent results.
- **Free tiers.** Groq's free tier allows about 8,000 tokens per minute per model, so the
  app caches results, limits simultaneous AI runs, and rate-limits each visitor. Render's
  free tier sleeps when idle, so the first load can take up to a minute.

## Run locally (Windows, cmd)

You need Python 3.12 or newer, a [Qloo hackathon key](https://hackathon.api.qloo.com), and
a free [Groq key](https://console.groq.com).

```
git clone https://github.com/Arunbalaji-dev/-taste-passport.git taste-passport
cd taste-passport
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` in a text editor and paste your two keys after `QLOO_API_KEY=` and
`LLM_API_KEY=`. Then start the app:

```
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 and click **Try an example**.

Run the tests (no keys or internet needed):

```
pytest
```

### Settings

| Variable | Required | Meaning |
|---|---|---|
| `QLOO_API_KEY` | yes | Your Qloo hackathon key |
| `QLOO_BASE_URL` | no | Defaults to `https://hackathon.api.qloo.com` (the hackathon key only works there) |
| `LLM_API_KEY` | yes | Your Groq key |
| `LLM_MODEL` | no | Groq model name; defaults to `openai/gpt-oss-120b` |

## Deploy on Render (free tier)

1. Push this repo to GitHub.
2. On [render.com](https://render.com), choose **New + > Web Service** and pick the repo.
3. Settings:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance type:** Free (the Python version comes from `.python-version`)
4. Under **Environment**, add `QLOO_API_KEY`, `LLM_API_KEY` and `QLOO_BASE_URL`.
   Never put keys in the repo.
5. After deploying, open `/api/health`. It should show `"status":"ok"` and both keys as
   `true` (it shows whether keys are set, never their values).

## Project layout

```
app/main.py      FastAPI: serves the site and the /api routes, rate limiting
app/qloo.py      Qloo tools (the only file that talks to Qloo): search, places, culture, cache, retries
app/agent.py     The LLM tool-calling loop, grounding check, result cache, AI-down fallback
app/prompts.py   The system prompt
static/          The website: HTML, CSS, plain JavaScript, Leaflet map
tests/           Tests for the API, the Qloo tools, and the agent (with a scripted fake LLM)
CLAUDE.md        Project rules and everything we confirmed about Qloo's real responses
```

## Built with

Python and FastAPI, Groq (OpenAI-compatible tool calling), the Qloo Insights API,
Leaflet and OpenStreetMap, Tailwind via CDN, and plain JavaScript. Everything runs on free
tiers.

## License

MIT. See [LICENSE](LICENSE).
