"""
Taste Passport - Qloo API quality test (Step 1, no LLM).

Run:
    pip install requests
    set QLOO_API_KEY=your_key          (Windows)
    export QLOO_API_KEY=your_key       (Mac/Linux)
    python test_qloo.py

Before running, confirm BASE_URL, the header name and parameter names
against the hackathon developer guide. Change them at the top if they differ.
Every raw response is saved in the raw/ folder so you can inspect it.
"""

import json
import os
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads QLOO_API_KEY from your .env file
except ImportError:
    pass  # falls back to a key set in the terminal

# ---- Settings: check these against the Qloo docs -------------------------
BASE_URL = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com")
API_KEY = os.getenv("QLOO_API_KEY")
HEADERS = {"X-Api-Key": API_KEY or ""}

CITIES = ["Berlin", "Tokyo", "Toronto", "Chennai"]

# Two very different taste profiles. If Qloo is good, they should get
# clearly different places in the same city.
PROFILES = {
    "A (mine)": [
        ("A.R. Rahman", "urn:entity:artist"),
        ("Interstellar", "urn:entity:movie"),
    ],
    "B (contrast)": [
        ("Metallica", "urn:entity:artist"),
        ("Fast & Furious", "urn:entity:movie"),
    ],
}
TAKE = 15
# ---------------------------------------------------------------------------

RAW = Path("raw")
RAW.mkdir(exist_ok=True)


def call(path, params, save_as):
    start = time.time()
    resp = requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=30)
    ms = int((time.time() - start) * 1000)
    if resp.status_code != 200:
        print(f"  !! {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        return None, ms
    data = resp.json()
    (RAW / f"{save_as}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data, ms


def search(name, entity_type):
    data, ms = call("/search", {"query": name, "types": entity_type, "take": 3},
                    f"search_{name.replace(' ', '_')}")
    results = (data or {}).get("results", [])
    print(f"  search '{name}' ({ms} ms):")
    for r in results:
        print(f"     - {r.get('name')}  [{r.get('entity_id')}]")
    return results[0]["entity_id"] if results else None


def places(city, entity_ids, label, extra=None):
    params = {
        "filter.type": "urn:entity:place",
        "filter.location.query": city,
        "take": TAKE,
    }
    if entity_ids:
        params["signal.interests.entities"] = ",".join(entity_ids)
    if extra:
        params.update(extra)
    data, ms = call("/v2/insights", params, f"places_{city}_{label}".replace(" ", "_"))
    entities = ((data or {}).get("results") or {}).get("entities", [])
    return entities, ms


def show(entities):
    for e in entities[:8]:
        aff = (e.get("query") or {}).get("affinity")
        pop = e.get("popularity")
        props = e.get("properties") or {}
        addr = props.get("address", "")
        print(f"     - {e.get('name')} | affinity={aff} | popularity={pop} | {addr[:50]}")


def overlap(a, b):
    ids_a = {e.get("entity_id") for e in a}
    ids_b = {e.get("entity_id") for e in b}
    if not ids_a or not ids_b:
        return None
    return round(len(ids_a & ids_b) / len(ids_a | ids_b), 2)


DIALS = {
    # First guesses to tune after seeing real data. Popularity is a 0-1 percentile.
    "comfort": {"signal.interests.entities.weight": "high", "filter.popularity.min": 0.7},
    "bridge": {},
    "adventure": {"signal.location.weight": "high", "filter.popularity.max": 0.6},
}


def dial_test(city, entity_ids):
    print(f"\n=== ADVENTURE DIAL TEST ({city}, profile A) ===")
    if not entity_ids:
        print(" No entity IDs for profile A - fix the search step first.")
        return
    results = {}
    for name, extra in DIALS.items():
        extra = {**extra, "feature.explainability": "true"}
        ents, ms = places(city, entity_ids, f"dial_{name}", extra)
        results[name] = ents
        pops = [e.get("popularity") for e in ents if isinstance(e.get("popularity"), (int, float))]
        avg = round(sum(pops) / len(pops), 2) if pops else None
        print(f" {name}: {len(ents)} results, avg popularity={avg}, {ms} ms")
        show(ents)
    print(f" Overlap comfort vs adventure: {overlap(results['comfort'], results['adventure'])}")
    print(" Good: adventure has lower avg popularity and a low overlap with comfort.")


def main():
    if not API_KEY:
        print("Set QLOO_API_KEY first.")
        return

    print("\n=== TEST 1: Do my favourites resolve to the right entities? ===")
    profile_ids = {}
    for label, items in PROFILES.items():
        print(f" Profile {label}")
        ids = [search(n, t) for n, t in items]
        profile_ids[label] = [i for i in ids if i]

    summary = []
    for city in CITIES:
        print(f"\n=== CITY: {city} ===")
        baseline, ms0 = places(city, [], "baseline")
        print(f" Baseline (no taste) - {len(baseline)} results, {ms0} ms")
        show(baseline)

        per_profile = {}
        for label, ids in profile_ids.items():
            ents, ms = places(city, ids, label)
            per_profile[label] = ents
            print(f" Profile {label} - {len(ents)} results, {ms} ms")
            show(ents)

        a, b = list(per_profile.values())[:2]
        has_scores = any((e.get("query") or {}).get("affinity") is not None for e in a)
        # The docs say invalid parameters are silently ignored. If the location
        # parameter is wrong, results will not be in the requested city.
        in_city = (
            round(sum(1 for e in a if city.lower() in json.dumps(e).lower()) / len(a), 2)
            if a else None
        )
        summary.append({
            "city": city,
            "results_A": len(a),
            "overlap_A_vs_B": overlap(a, b),
            "overlap_A_vs_baseline": overlap(a, baseline),
            "affinity_present": has_scores,
            "in_city": in_city,
        })

    print("\n=== SCORECARD ===")
    print(f"{'city':10} {'results':>8} {'A vs B':>8} {'A vs base':>10} {'affinity':>9} {'in_city':>8}")
    for s in summary:
        print(f"{s['city']:10} {s['results_A']:>8} {str(s['overlap_A_vs_B']):>8} "
              f"{str(s['overlap_A_vs_baseline']):>10} {str(s['affinity_present']):>9} "
              f"{str(s['in_city']):>8}")
    print("\nOverlap: 0 = completely different lists, 1 = identical lists.")
    print("in_city: share of results that mention the requested city. Near 0 means the")
    print("location parameter is probably being silently ignored - check the docs.")
    dial_test(CITIES[0], list(profile_ids.values())[0])
    print("\nRaw JSON saved in ./raw - paste one file back to your mentor.")


if __name__ == "__main__":
    main()
