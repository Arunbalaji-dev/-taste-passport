import pytest

from app import qloo

# Small fake responses that copy the real shape seen in raw/.
FAKE_SEARCH = {"results": [{
    "name": "Interstellar", "entity_id": "ID-MOVIE", "types": ["urn:entity:movie"],
    "popularity": 0.9, "disambiguation": "2014 film",
}]}

FAKE_INSIGHTS = {"success": True, "results": {"entities": [{
    "name": "Bar Panorama Berlin", "entity_id": "ID-PLACE",
    "popularity": 0.43, "location": {"lat": 52.5, "lon": 13.3},
    "tags": [{"id": "t1", "name": "Small plates"}],
    "properties": {"address": "Lewishamstrasse 1", "description": "Cocktail bar.",
                   "images": [{"url": "https://img/x.jpg"}]},
    "query": {"affinity": 0.82, "explainability": {
        "signal.interests.entities": [{"entity_id": "ID-MOVIE", "score": 0.55}]}},
}]}}


def test_search_entities_cleans_results(monkeypatch):
    monkeypatch.setattr(qloo, "_get", lambda path, params: FAKE_SEARCH)
    result = qloo.search_entities("Interstellar", "urn:entity:movie")
    assert result[0]["entity_id"] == "ID-MOVIE"
    assert result[0]["type"] == "urn:entity:movie"


def test_find_places_cleans_results_and_sends_params(monkeypatch):
    seen = {}

    def fake_get(path, params):
        seen["path"], seen["params"] = path, params
        return FAKE_INSIGHTS

    monkeypatch.setattr(qloo, "_get", fake_get)
    places = qloo.find_places("Berlin", ["ID-MOVIE"], dial="adventure")

    assert seen["path"] == "/v2/insights"
    assert seen["params"]["filter.type"] == "urn:entity:place"
    assert seen["params"]["filter.location.query"] == "Berlin"
    assert seen["params"]["filter.popularity.max"] == 0.5  # adventure preset applied
    # default place types are sent as one comma-separated (OR) list
    assert seen["params"]["filter.tags"] == ",".join(qloo.DEFAULT_PLACE_TAGS)
    place = places[0]
    assert place["name"] == "Bar Panorama Berlin"
    assert place["image"] == "https://img/x.jpg"
    assert place["affinity"] == 0.82
    assert place["contributions"][0]["entity_id"] == "ID-MOVIE"


def test_dial_bands_are_ordered(monkeypatch):
    sent = []
    monkeypatch.setattr(qloo, "_get", lambda path, params: sent.append(params) or FAKE_INSIGHTS)
    for dial in ["comfort", "bridge", "adventure"]:
        qloo.find_places("Berlin", ["ID"], dial=dial)
    comfort, bridge, adventure = sent
    assert comfort["filter.popularity.min"] >= bridge["filter.popularity.max"]
    assert bridge["filter.popularity.min"] >= adventure["filter.popularity.max"]


def test_empty_tags_means_no_type_filter(monkeypatch):
    sent = []
    monkeypatch.setattr(qloo, "_get", lambda path, params: sent.append(params) or FAKE_INSIGHTS)
    qloo.find_places("Berlin", ["ID"], tags=None)
    assert "filter.tags" not in sent[0]


def test_place_with_null_list_entries_does_not_crash(monkeypatch):
    # Seen in real Chennai data: a null item inside "images".
    entity = {"name": "X", "entity_id": "ID", "properties": {"images": [None]}, "tags": [None]}
    monkeypatch.setattr(qloo, "_get", lambda path, params: {"results": {"entities": [entity]}})
    place = qloo.find_places("Chennai", ["ID"])[0]
    assert place["image"] is None and place["tags"] == []


def test_find_local_culture_uses_signal_location_not_filter(monkeypatch):
    seen = {}
    artist = {"name": "Hans Zimmer", "entity_id": "ID-ARTIST",
              "properties": {"image": {"url": "https://img/a.jpg"}, "description": "Composer."},
              "query": {"affinity": 0.9}}
    monkeypatch.setattr(qloo, "_get", lambda path, params: seen.update(params=params)
                        or {"results": {"entities": [artist]}})
    result = qloo.find_local_culture("Berlin", ["ID"], "artist")
    assert seen["params"]["filter.type"] == "urn:entity:artist"
    assert seen["params"]["signal.location.query"] == "Berlin"
    assert "filter.location.query" not in seen["params"]  # silently ignored by Qloo here
    assert result[0]["image"] == "https://img/a.jpg"


def test_unknown_culture_type_raises_friendly_error():
    with pytest.raises(qloo.QlooError):
        qloo.find_local_culture("Berlin", ["ID"], "video_game")  # Qloo returns 400 for this


def test_find_places_empty_result_is_empty_list(monkeypatch):
    monkeypatch.setattr(qloo, "_get", lambda path, params: {"results": {"entities": []}})
    assert qloo.find_places("Nowhere", ["ID"]) == []


def test_unknown_dial_raises_friendly_error():
    with pytest.raises(qloo.QlooError):
        qloo.find_places("Berlin", ["ID"], dial="extreme")


def test_missing_key_raises_friendly_error(monkeypatch):
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    with pytest.raises(qloo.QlooError):
        qloo.search_entities("x", "urn:entity:movie")
