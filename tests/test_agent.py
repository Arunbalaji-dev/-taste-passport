import json

import pytest

from app import agent, qloo

MOVIE = {"entity_id": "ID-MOVIE", "name": "Interstellar", "type": "urn:entity:movie",
         "popularity": 0.9, "disambiguation": "2014"}


def place(entity_id, name, **extra):
    return {"entity_id": entity_id, "name": name, "address": "Somewhere 1", "description": "A bar.",
            "image": None, "lat": 52.5, "lon": 13.4, "popularity": 0.4, "affinity": 0.8,
            "tags": ["Bar"], "contributions": [{"entity_id": "ID-MOVIE", "score": 0.6}], **extra}


def tool_call(call_id, name, args):
    return {"content": None, "tool_calls": [
        {"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}]}


def scripted_llm(*replies):
    """A fake LLM that returns the given replies one by one."""
    replies = list(replies)
    return lambda messages, tools: replies.pop(0)


@pytest.fixture
def fake_qloo(monkeypatch):
    monkeypatch.setattr(qloo, "search_entities", lambda name, t, take=3: [MOVIE])
    seen = {}

    def fake_find_places(city, ids, dial="bridge", take=15, tags=None):
        seen["dial"] = dial
        return [place("P1", "Bar One"), place("P2", "Bar Two"), place("P3", "bar one")]  # P3 repeats a name

    monkeypatch.setattr(qloo, "find_places", fake_find_places)
    monkeypatch.setattr(qloo, "find_local_culture", lambda *a, **k: [])
    return seen


def test_happy_path_builds_cards_from_qloo_data(monkeypatch, fake_qloo):
    final = json.dumps({"picks": [{"entity_id": "P1", "note": "Fits your taste."}]})
    monkeypatch.setattr(agent, "llm_call", scripted_llm(
        tool_call("1", "search_entities", {"name": "Interstellar", "entity_type": "movie"}),
        tool_call("2", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"], "dial": "comfort"}),
        {"content": final}))
    result = agent.run_passport("Interstellar", "Berlin", "adventure")
    assert fake_qloo["dial"] == "adventure"  # the user's dial wins over the LLM's
    assert [p["name"] for p in result["places"]] == ["Bar One"]
    assert result["places"][0]["note"] == "Fits your taste."
    assert result["places"][0]["fits"] == [{"name": "Interstellar", "share": 0.6, "person": None}]
    assert result["dropped"] == 0 and not result["fallback"]


def test_grounding_drops_picks_not_from_qloo(monkeypatch, fake_qloo):
    final = json.dumps({"picks": [
        {"entity_id": "INVENTED", "note": "A place the AI made up."},
        {"entity_id": "P2", "note": "Real."},
        {"entity_id": "P3", "note": "Repeated name was removed, so this id is unknown."}]})
    monkeypatch.setattr(agent, "llm_call", scripted_llm(
        tool_call("1", "search_entities", {"name": "Interstellar", "entity_type": "movie"}),
        tool_call("2", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),
        {"content": "Here you go: " + final}))
    result = agent.run_passport("Interstellar", "Berlin", "bridge")
    assert [p["name"] for p in result["places"]] == ["Bar Two"]
    assert result["dropped"] == 2


def test_unparseable_answer_falls_back_to_qloo_results(monkeypatch, fake_qloo):
    monkeypatch.setattr(agent, "llm_call", scripted_llm(
        tool_call("1", "search_entities", {"name": "Interstellar", "entity_type": "movie"}),
        tool_call("2", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),
        {"content": "Sorry, no JSON today"}))
    result = agent.run_passport("Interstellar", "Berlin", "bridge")
    assert result["fallback"] is True
    assert [p["name"] for p in result["places"]] == ["Bar One", "Bar Two"]
    assert all(p["note"] is None for p in result["places"])


def test_no_favourites_found_gives_friendly_message(monkeypatch):
    monkeypatch.setattr(qloo, "search_entities", lambda *a, **k: [])
    monkeypatch.setattr(agent, "llm_call", scripted_llm(
        tool_call("1", "search_entities", {"name": "Zzzz", "entity_type": "movie"}),
        {"content": json.dumps({"picks": []})}))
    result = agent.run_passport("Zzzz", "Berlin", "bridge")
    assert result["places"] == [] and "couldn't find" in result["message"]


def test_loop_stops_after_max_steps(monkeypatch, fake_qloo):
    endless = lambda messages, tools: tool_call("x", "search_entities", {"name": "A", "entity_type": "movie"})
    monkeypatch.setattr(agent, "llm_call", endless)
    result = agent.run_passport("A", "Berlin", "bridge")  # must return, not hang
    assert result["places"] == []


def test_qloo_error_goes_back_to_llm_not_crash(monkeypatch):
    def boom(*a, **k):
        raise qloo.QlooError("Qloo is busy")
    monkeypatch.setattr(qloo, "search_entities", boom)
    registry = agent.Registry()
    result = agent.run_tool("search_entities", {"name": "A", "entity_type": "movie"}, registry, "bridge")
    assert result == {"error": "Qloo is busy"}


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


def test_rate_limit_switches_to_backup_model(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    models_tried = []

    def fake_post(model, messages, tools, api_key):
        models_tried.append(model)
        return FakeResponse(429 if len(models_tried) == 1 else 200)

    monkeypatch.setattr(agent, "_post_to_groq", fake_post)
    assert agent.llm_call([], [])["content"] == "ok"
    assert models_tried == [agent.DEFAULT_MODEL, agent.FALLBACK_MODEL]


def test_rate_limit_everywhere_gives_friendly_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setattr(agent, "_post_to_groq", lambda *a: FakeResponse(429, {"retry-after": "300"}))
    with pytest.raises(agent.AgentError, match="busy"):
        agent.llm_call([], [])  # waiting 300s is too long, so it gives up at once


def test_resolved_favourites_are_reused_without_searching(monkeypatch, fake_qloo):
    seen_messages = []
    final = json.dumps({"picks": [{"entity_id": "P1", "note": "ok"}]})

    def llm(messages, tools):
        seen_messages.append(messages[1]["content"])
        if len(seen_messages) == 1:
            return tool_call("1", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]})
        return {"content": final}

    monkeypatch.setattr(agent, "llm_call", llm)
    resolved = [{"entity_id": "ID-MOVIE", "name": "Interstellar", "type": "x", "person": None}]
    result = agent.run_passport("", "Berlin", "bridge", resolved=resolved)
    assert "do NOT call search_entities" in seen_messages[0]
    assert result["favourites"][0]["name"] == "Interstellar"
    assert result["places"][0]["fits"][0]["name"] == "Interstellar"


def test_group_passport_tags_each_favourite_with_its_person(monkeypatch, fake_qloo):
    final = json.dumps({"picks": [{"entity_id": "P1", "note": "ok"}]})
    monkeypatch.setattr(agent, "llm_call", scripted_llm(
        tool_call("1", "search_entities", {"name": "Interstellar", "entity_type": "movie", "person": "Ana"}),
        tool_call("2", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),
        {"content": final}))
    people = [{"name": "Ana", "favourites": "Interstellar"}, {"name": "Ben", "favourites": "Metallica"}]
    result = agent.run_passport("", "Berlin", "bridge", people=people)
    assert result["places"][0]["fits"] == [{"name": "Interstellar", "share": 0.6, "person": "Ana"}]


def test_unknown_dial_rejected():
    with pytest.raises(agent.AgentError):
        agent.run_passport("x", "Berlin", "extreme")
