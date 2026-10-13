"""LLM agent loop - Phase 3.

One LLM, three Qloo tools, one plain loop. The LLM decides which tools to call
and writes a short note per pick. Everything shown to the user (names, images,
scores, "fits you" shares) is filled in by CODE from Qloo results, and any pick
that did not come from a Qloo result is dropped (the grounding check).
"""

import json
import os
import time

import httpx
from dotenv import load_dotenv

from app import qloo
from app.prompts import SYSTEM_PROMPT

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"  # change with the LLM_MODEL env var
FALLBACK_MODEL = "openai/gpt-oss-20b"  # used when the main model is rate limited
MAX_WAIT_SECONDS = 20  # longest we will pause on a rate limit before giving up
MAX_STEPS = 8  # safety limit so the loop can never run forever
MAX_PLACE_PICKS = 8
MAX_CULTURE_PICKS = 3

ENTITY_TYPES = ["artist", "movie", "tv_show", "brand", "book", "podcast", "video_game"]

TOOLS = [
    {"type": "function", "function": {
        "name": "search_entities",
        "description": "Look up one favourite by name and get its Qloo entity_id.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "entity_type": {"type": "string", "enum": ENTITY_TYPES},
            "person": {"type": "string", "description": "Whose favourite this is, only if several people are listed."},
        }, "required": ["name", "entity_type"]},
    }},
    {"type": "function", "function": {
        "name": "find_places",
        "description": "Find places (food, drink, culture, parks, music venues) in a city that fit the taste.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"},
            "entity_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["city", "entity_ids"]},
    }},
    {"type": "function", "function": {
        "name": "find_local_culture",
        "description": "Find artists, brands, TV shows or podcasts that Qloo ranks higher for this city and taste.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"},
            "entity_ids": {"type": "array", "items": {"type": "string"}},
            "culture_type": {"type": "string", "enum": qloo.CULTURE_TYPES},
        }, "required": ["city", "entity_ids"]},
    }},
]


class AgentError(Exception):
    """A problem running the agent. The message is safe to show to the user."""


def _post_to_groq(model, messages, tools, api_key):
    try:
        return httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.2,
                # These models "think" before answering; low keeps it fast and
                # saves tokens (the free tier allows only 8,000 per minute).
                "reasoning_effort": "low",
            },
            timeout=60,
        )
    except httpx.TimeoutException:
        raise AgentError("The AI model took too long to answer. Please try again.")
    except httpx.HTTPError:
        raise AgentError("Could not reach the AI model. Please try again.")


def llm_call(messages, tools):
    """The ONLY place that talks to the LLM. Swap providers by changing this function.

    Groq's free tier limits each model separately (8,000 tokens per minute), so on
    a rate limit (429) we try the backup model, then wait briefly and retry once.
    """
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise AgentError("The LLM API key is not configured on the server.")
    models = [os.getenv("LLM_MODEL", DEFAULT_MODEL), FALLBACK_MODEL]
    response = None
    for attempt in range(2):
        for model in models:
            response = _post_to_groq(model, messages, tools, api_key)
            if response.status_code != 429:
                break
        if response.status_code != 429:
            break
        if attempt == 0:  # both models are limited: wait a little, then try again
            try:
                wait = float(response.headers.get("retry-after", MAX_WAIT_SECONDS))
            except ValueError:
                wait = MAX_WAIT_SECONDS
            if wait > MAX_WAIT_SECONDS:
                break
            time.sleep(wait + 0.5)
    if response.status_code == 429:
        raise AgentError("The AI model is busy right now (rate limit). Please wait a minute and retry.")
    if response.status_code != 200:
        raise AgentError(f"The AI model returned an error ({response.status_code}).")
    return response.json()["choices"][0]["message"]


# ---------- helpers that keep a record of everything Qloo returned ----------

class Registry:
    """Remembers every Qloo result seen in this request (the grounding source)."""

    def __init__(self):
        self.favourites = {}  # entity_id -> {entity_id, name, type}
        self.items = {}       # entity_id -> cleaned place/culture dict + kind + fits
        self.order = []       # entity_ids in the order Qloo returned them, per kind

    def fits(self, contributions):
        """Turn Qloo's explainability scores into [{"name": favourite, "share": 0-1}]."""
        out = []
        for c in contributions or []:
            fav = self.favourites.get(c.get("entity_id"))
            if fav and c.get("score") is not None:
                out.append({"name": fav["name"], "share": round(c["score"], 2),
                            "person": fav.get("person")})
        return out

    def add_items(self, items, kind):
        """Store results (skipping repeated names, e.g. many 'Tim Hortons')."""
        seen_names = {i["name"].lower() for i in self.items.values() if i["kind"] == kind}
        kept = []
        for item in items:
            name = (item.get("name") or "").lower()
            if not name or name in seen_names or not item.get("entity_id"):
                continue
            seen_names.add(name)
            item = {**item, "kind": kind, "fits": self.fits(item.get("contributions"))}
            self.items[item["entity_id"]] = item
            kept.append(item)
        return kept


def _short_for_llm(item):
    """A small version of a result for the LLM (saves tokens on the free tier)."""
    return {
        "entity_id": item["entity_id"],
        "name": item["name"],
        "address": item.get("address"),
        "popularity": None if item.get("popularity") is None else round(item["popularity"], 2),
        "affinity": None if item.get("affinity") is None else round(item["affinity"], 2),
        "tags": item.get("tags", [])[:3],
        "description": (item.get("description") or "")[:100],
        "fits": item["fits"],
    }


def run_tool(name, args, registry, dial):
    """Run one tool the LLM asked for. Returns a JSON-able result for the LLM."""
    try:
        if name == "search_entities":
            hits = qloo.search_entities(args["name"], f"urn:entity:{args['entity_type']}", take=3)
            for hit in hits[:1]:  # the top hit is what we treat as the user's favourite
                registry.favourites[hit["entity_id"]] = {**hit, "person": args.get("person")}
            return [{k: h[k] for k in ("entity_id", "name", "type", "disambiguation")} for h in hits]
        if name == "find_places":
            # The dial always comes from the user, never from the LLM.
            # Only 10 results: every result is re-sent to the LLM on each step,
            # and the free tier allows just 8,000 tokens per minute.
            found = qloo.find_places(args["city"], args["entity_ids"], dial=dial, take=10)
            return [_short_for_llm(i) for i in registry.add_items(found, "place")]
        if name == "find_local_culture":
            found = qloo.find_local_culture(
                args["city"], args["entity_ids"], args.get("culture_type", "artist"), take=5)
            return [_short_for_llm(i) for i in registry.add_items(found, "culture")]
        return {"error": f"Unknown tool: {name}"}
    except qloo.QlooError as err:
        return {"error": str(err)}
    except (KeyError, TypeError):
        return {"error": "Bad tool arguments."}


# ---------- grounding check ----------

def _parse_picks(text):
    """Pull the {"picks": [...]} JSON out of the LLM's final message."""
    if not text:
        return []
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        picks = json.loads(text[start:end + 1]).get("picks", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return picks if isinstance(picks, list) else []


def ground_picks(picks, registry):
    """Keep only picks whose entity_id really came from Qloo. Returns (cards, dropped).

    A card is built from the Qloo data, not from anything the LLM wrote; the LLM
    only supplies the short note.
    """
    cards, used, dropped = [], set(), 0
    counts = {"place": 0, "culture": 0}
    limits = {"place": MAX_PLACE_PICKS, "culture": MAX_CULTURE_PICKS}
    for pick in picks:
        item = registry.items.get(pick.get("entity_id")) if isinstance(pick, dict) else None
        if item is None or item["entity_id"] in used or counts[item["kind"]] >= limits[item["kind"]]:
            dropped += 1
            continue
        used.add(item["entity_id"])
        counts[item["kind"]] += 1
        note = pick.get("note")
        cards.append({**item, "note": note if isinstance(note, str) else None})
    return cards, dropped


# ---------- the agent loop ----------

def _user_message(favourites_text, city, people, registry):
    """Describe the request to the LLM. Already-resolved favourites skip the search step."""
    if registry.favourites:
        lines = [f"- {f['name']}" + (f" ({f['person']})" if f.get("person") else "") + f", entity_id {f['entity_id']}"
                 for f in registry.favourites.values()]
        return (f"City: {city}\nFavourites already resolved (do NOT call search_entities):\n" + "\n".join(lines))
    if people:
        lines = [f"- {p['name']}: {p['favourites']}" for p in people]
        return f"City: {city}\nSeveral people, pass each one's name as `person` in search_entities:\n" + "\n".join(lines)
    return f"City: {city}\nMy favourites: {favourites_text}"


def run_passport(favourites_text, city, dial, people=None, resolved=None):
    """Main entry point: favourites + city + dial -> grounded result.

    people:   optional [{"name", "favourites"}] for a Group Passport.
    resolved: optional favourites found by an earlier run (so switching the dial
              does not search again, which saves LLM tokens).
    """
    if dial not in qloo.DIALS:
        raise AgentError("Unknown dial setting.")
    registry = Registry()
    for fav in resolved or []:
        registry.favourites[fav["entity_id"]] = fav
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(favourites_text, city, people, registry)},
    ]
    final_text = None
    for _ in range(MAX_STEPS):
        reply = llm_call(messages, TOOLS)
        calls = reply.get("tool_calls")
        if not calls:
            final_text = reply.get("content")
            break
        messages.append({"role": "assistant", "content": reply.get("content"), "tool_calls": calls})
        for call in calls:
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_tool(call["function"]["name"], args, registry, dial)
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False)})

    cards, dropped = ground_picks(_parse_picks(final_text), registry)
    fallback = False
    if not cards and registry.items:
        # The LLM gave nothing usable: show Qloo's own top results, with no notes.
        fallback = True
        for kind, limit in (("place", MAX_PLACE_PICKS), ("culture", MAX_CULTURE_PICKS)):
            cards += [{**i, "note": None} for i in registry.items.values() if i["kind"] == kind][:limit]

    message = None
    if not registry.favourites:
        message = "I couldn't find any of your favourites in Qloo. Try more well-known titles or artists."
    elif not cards:
        message = f"Qloo returned no results for {city} with these favourites. Try a larger city or other favourites."
    return {
        "city": city,
        "dial": dial,
        "favourites": list(registry.favourites.values()),
        "places": [c for c in cards if c["kind"] == "place"],
        "culture": [c for c in cards if c["kind"] == "culture"],
        "dropped": dropped,
        "fallback": fallback,
        "message": message,
    }
