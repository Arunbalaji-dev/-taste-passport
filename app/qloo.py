"""Qloo tool functions - Phase 2.

This is the ONLY file that talks to Qloo. Field names below were confirmed
from real responses saved in raw/ (see CLAUDE.md).
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

TIMEOUT_SECONDS = 20

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


class QlooError(Exception):
    """A problem talking to Qloo. The message is safe to show to the user."""


def _get(path, params):
    """One GET request to Qloo. Turns every failure into a friendly QlooError."""
    base_url = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com")
    api_key = os.getenv("QLOO_API_KEY")
    if not api_key:
        raise QlooError("The Qloo API key is not configured on the server.")
    try:
        response = httpx.get(
            base_url + path,
            params=params,
            headers={"X-Api-Key": api_key},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        raise QlooError("Qloo took too long to answer. Please try again.")
    except httpx.HTTPError:
        raise QlooError("Could not reach Qloo. Please try again.")

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


def _clean_place(entity):
    """Keep only the fields we show or explain from, in a simple flat shape."""
    props = entity.get("properties") or {}
    query = entity.get("query") or {}
    # Real data sometimes has empty/null entries in lists, so skip those.
    image = next((i["url"] for i in props.get("images") or [] if i and i.get("url")), None)
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
    return [_clean_place(e) for e in entities]
