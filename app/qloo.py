"""Qloo tool functions - Phase 2.

This is the ONLY file that talks to Qloo. Field names below were confirmed
from real responses saved in raw/ (see CLAUDE.md).
"""

import logging
import os
import threading
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("taste-passport")  # never log keys, only paths and counts

TIMEOUT_SECONDS = 15

# Adventure Dial presets, tuned on live Berlin and Tokyo data. The dial works by
# popularity band (0-1 percentile, 1 = most popular). In both cities the three
# bands gave zero overlapping places while affinity stayed around 0.7-0.8.
DIALS = {
    "comfort": {"filter.popularity.min": 0.85},
    "bridge": {"filter.popularity.min": 0.5, "filter.popularity.max": 0.85},
    "adventure": {"filter.popularity.max": 0.5, "signal.location.weight": "high"},
}


# Default kinds of place: somewhere to eat/drink (restaurant includes bar, cafe
# and bakery), see art, relax outside, or hear live music. Without a filter,
# Qloo "place" also returns hotels, gyms, train stations and similar.
DEFAULT_PLACE_TAGS = [
    "urn:tag:genre:place:restaurant",
    "urn:tag:genre:place:museum",
    "urn:tag:genre:place:park",
    "urn:tag:genre:place:live_music_venue",
]


# Types checked on live data to respond to signal.location.query.
CULTURE_TYPES = ["artist", "brand", "tv_show", "podcast"]


class QlooError(Exception):
    """A problem talking to Qloo. The message is safe to show to the user."""


# ---------- cache and retries (Phase 5) ----------

CACHE_SECONDS = 3600  # Qloo's data changes slowly, so an hour is safe
CACHE_MAX_ENTRIES = 500  # keeps memory small on the free host
RETRIES = 2  # extra attempts after a timeout or a Qloo server error
RETRY_DELAY_SECONDS = 0.7
_cache = {}  # key -> (expires_at, data)
_cache_lock = threading.Lock()


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _cache_key(path, params):
    return path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))


def _request(path, params):
    """One real request to Qloo, retrying timeouts and Qloo-side server errors."""
    base_url = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com")
    api_key = os.getenv("QLOO_API_KEY")
    if not api_key:
        raise QlooError("The Qloo API key is not configured on the server.")
    for attempt in range(RETRIES + 1):
        last_try = attempt == RETRIES
        try:
            response = httpx.get(
                base_url + path,
                params=params,
                headers={"X-Api-Key": api_key},
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException:
            if last_try:
                raise QlooError("Qloo took too long to answer. Please try again.")
        except httpx.HTTPError:
            if last_try:
                raise QlooError("Could not reach Qloo. Please try again.")
        else:
            # 5xx means Qloo had a hiccup, so trying again often works.
            # 400, 401, 403 and 429 will not improve by retrying, so return at once.
            if response.status_code not in (500, 502, 503, 504) or last_try:
                return response
        logger.warning("Qloo request to %s failed (attempt %d), retrying", path, attempt + 1)
        time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))


def _get(path, params):
    """GET from Qloo with a cache. Turns every failure into a friendly QlooError."""
    key = _cache_key(path, params)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
    data = _handle(_request(path, params))
    with _cache_lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            _cache.pop(next(iter(_cache)))  # drop the oldest entry
        _cache[key] = (time.time() + CACHE_SECONDS, data)
    return data


def _handle(response):
    """Turn a Qloo HTTP response into data, or a friendly QlooError."""
    if response.status_code == 400:
        raise QlooError("Qloo could not understand that request (is the city name right?).")
    if response.status_code == 429:
        raise QlooError("Qloo is busy right now (rate limit). Please wait a moment and retry.")
    if response.status_code in (401, 403):
        raise QlooError("Qloo rejected the request (API key or permissions problem).")
    if response.status_code != 200:
        raise QlooError(f"Qloo returned an unexpected error ({response.status_code}).")
    return response.json()


def search_entities(name, entity_type, take=3):
    """Turn a name ("Interstellar") into Qloo entities with IDs.

    entity_type example: "urn:entity:movie" or "urn:entity:artist".
    Returns a list of {entity_id, name, type, popularity, disambiguation}.
    """
    data = _get("/search", {"query": name, "types": entity_type, "take": take})
    results = []
    for item in data.get("results") or []:
        results.append({
            "entity_id": item.get("entity_id"),
            "name": item.get("name"),
            # Search results use "types" (a list), unlike insights results.
            "type": (item.get("types") or [entity_type])[0],
            "popularity": item.get("popularity"),
            "disambiguation": item.get("disambiguation"),
        })
    return results


def _clean_entity(entity):
    """Keep only the fields we show or explain from, in a simple flat shape.

    Works for places and for artists/brands/shows/podcasts (fields that don't
    apply, like address, simply come back as None).
    """
    props = entity.get("properties") or {}
    query = entity.get("query") or {}
    # Real data sometimes has empty/null entries in lists, so skip those.
    # Places keep photos in "images" (a list); other types use "image" (one dict).
    image = next((i["url"] for i in props.get("images") or [] if i and i.get("url")), None)
    if not image and isinstance(props.get("image"), dict):
        image = props["image"].get("url")
    tags = [t["name"] for t in entity.get("tags") or [] if t and t.get("name")][:6]
    location = entity.get("location") or {}
    return {
        "entity_id": entity.get("entity_id"),
        "name": entity.get("name"),
        "address": props.get("address"),
        "description": props.get("description"),
        "image": image,
        "lat": location.get("lat"),
        "lon": location.get("lon"),
        "popularity": entity.get("popularity"),
        "affinity": query.get("affinity"),
        "tags": tags,
        # Which of the user's favourites drove this result, and how much (0-1).
        # This is what "why this fits you" is built from.
        "contributions": (query.get("explainability") or {}).get("signal.interests.entities", []),
    }


def find_places(city, entity_ids, dial="bridge", take=15, tags=DEFAULT_PLACE_TAGS):
    """Find places in `city` that match the taste given as Qloo entity IDs.

    dial: "comfort", "bridge" or "adventure" (see DIALS).
    tags: list of tag IDs from /v2/tags limiting the kind of place. Verified on
          live data: a comma-separated list means OR, and a parent tag also
          matches its children. Pass None or [] for no type filter.
    Returns a list of cleaned place dicts (possibly empty).
    """
    if dial not in DIALS:
        raise QlooError(f"Unknown dial setting: {dial}")
    params = {
        "filter.type": "urn:entity:place",
        "filter.location.query": city,
        "signal.interests.entities": ",".join(entity_ids),
        "feature.explainability": "true",
        "take": take,
        **DIALS[dial],
    }
    if tags:
        params["filter.tags"] = ",".join(tags)
    data = _get("/v2/insights", params)
    entities = (data.get("results") or {}).get("entities") or []
    return [_clean_entity(e) for e in entities]


def find_local_culture(city, entity_ids, culture_type="artist", take=10):
    """Find artists, brands, TV shows or podcasts that Qloo ties to `city`.

    Verified on live data: filter.location is silently ignored for these types
    (Berlin and Tokyo gave identical lists), but signal.location.query does
    change the results (e.g. different brands, a Berlin-set show for Berlin).
    So this is "what Qloo ranks higher for this city and this taste", not a
    guarantee that the artist or brand is from the city.
    """
    if culture_type not in CULTURE_TYPES:
        raise QlooError(f"Unknown culture type: {culture_type}")
    data = _get("/v2/insights", {
        "filter.type": f"urn:entity:{culture_type}",
        "signal.interests.entities": ",".join(entity_ids),
        "signal.location.query": city,
        "feature.explainability": "true",
        "take": take,
    })
    entities = (data.get("results") or {}).get("entities") or []
    return [_clean_entity(e) for e in entities]
