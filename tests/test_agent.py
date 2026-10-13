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
        tool_call("2", "search_entities", {"name": "Metallica", "entity_type": "artist", "person": "Ben"}),
        tool_call("3", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),
        {"content": final}))
    people = [{"name": "Ana", "favourites": "Interstellar"}, {"name": "Ben", "favourites": "Metallica"}]
    # Each name must resolve to its own entity (the shared fake returns the same one for every name).
    monkeypatch.setattr(qloo, "search_entities", lambda name, t, take=3: [
        {**MOVIE, "entity_id": "ID-MOVIE" if name == "Interstellar" else "ID-MET", "name": name}])
    result = agent.run_passport("", "Berlin", "bridge", people=people)
    assert result["places"][0]["fits"] == [{"name": "Interstellar", "share": 0.6, "person": "Ana"}]


def test_skipped_favourite_is_sent_back_to_the_ai_once(monkeypatch, fake_qloo):
    """Real bug: the AI silently skipped 'Fast & Furious' in a Group Passport."""
    final = json.dumps({"picks": [{"entity_id": "P1", "note": "ok"}]})
    seen_tool_results = []

    def llm(messages, tools):
        if messages[-1]["role"] == "tool":
            seen_tool_results.append(messages[-1]["content"])
        step = len(seen_tool_results)
        return [tool_call("1", "search_entities", {"name": "Metallica", "entity_type": "artist"}),
                tool_call("2", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),   # skipped one!
                tool_call("3", "search_entities", {"name": "Fast & Furious", "entity_type": "movie"}),
                tool_call("4", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),
                {"content": final}][step]

    monkeypatch.setattr(agent, "llm_call", llm)
    result = agent.run_passport("Metallica, Fast & Furious", "Berlin", "bridge")
    assert "Fast & Furious" in seen_tool_results[1]  # the AI was told what it skipped
    assert [p["name"] for p in result["places"]] == ["Bar One"]  # and it recovered


def test_nudge_happens_only_once_and_never_for_resolved_favourites(monkeypatch, fake_qloo):
    registry = agent.Registry()
    registry.expected = ["Metallica", "Fast & Furious"]
    first = agent.run_tool("find_places", {"city": "Berlin", "entity_ids": ["x"]}, registry, "bridge")
    assert "error" in first
    second = agent.run_tool("find_places", {"city": "Berlin", "entity_ids": ["x"]}, registry, "bridge")
    assert isinstance(second, list)  # a second attempt goes through, so it can never loop

    monkeypatch.setattr(agent, "llm_call", scripted_llm(
        tool_call("1", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),
        {"content": json.dumps({"picks": [{"entity_id": "P1", "note": "ok"}]})}))
    resolved = [{"entity_id": "ID-MOVIE", "name": "Interstellar", "type": "x", "person": None}]
    result = agent.run_passport("Metallica, Fast & Furious", "Berlin", "bridge", resolved=resolved)
    assert result["places"]  # resolved favourites skip the check entirely


def test_missing_check_ignores_spelling_and_punctuation():
    registry = agent.Registry()
    registry.expected = ["A.R. Rahman", "Fast & Furious", "studio ghibli"]
    registry.searched = ["AR Rahman", "Fast and Furious"]
    assert registry.missing_favourites() == ["studio ghibli"]  # spelling and "&" vs "and" do not matter


def test_same_search_is_answered_from_cache_without_the_ai(monkeypatch, fake_qloo):
    final = json.dumps({"picks": [{"entity_id": "P1", "note": "ok"}]})
    calls = []

    def llm(messages, tools):
        calls.append(1)
        steps = [tool_call("1", "search_entities", {"name": "Interstellar", "entity_type": "movie"}),
                 tool_call("2", "find_places", {"city": "Berlin", "entity_ids": ["ID-MOVIE"]}),
                 {"content": final}]
        return steps[(len(calls) - 1) % 3]  # each search takes 3 AI calls: search, places, answer

    monkeypatch.setattr(agent, "llm_call", llm)
    first = agent.run_passport("Interstellar", "Berlin", "bridge")
    second = agent.run_passport("  interstellar ", "berlin", "bridge")  # same search, different spelling
    assert second == first and len(calls) == 3  # the AI ran only for the first search
    agent.run_passport("Interstellar", "Berlin", "adventure")  # another dial is a new search
    assert len(calls) > 3


def test_ai_down_still_shows_qloo_results_when_favourites_are_known(monkeypatch, fake_qloo):
    def llm(messages, tools):
        raise agent.AgentError("The AI model is busy right now (rate limit).")

    monkeypatch.setattr(agent, "llm_call", llm)
    resolved = [{"entity_id": "ID-MOVIE", "name": "Interstellar", "type": "x", "person": None}]
    result = agent.run_passport("", "Berlin", "bridge", resolved=resolved)
    assert result["fallback"] is True
    assert [p["name"] for p in result["places"]] == ["Bar One", "Bar Two"]
    assert all(p["note"] is None for p in result["places"])
    assert agent._result_cache == {}  # a degraded answer is never cached


def test_ai_down_with_nothing_found_yet_raises_friendly_error(monkeypatch):
    def llm(messages, tools):
        raise agent.AgentError("The AI model is busy right now (rate limit).")

    monkeypatch.setattr(agent, "llm_call", llm)
    with pytest.raises(agent.AgentError, match="busy"):
        agent.run_passport("Interstellar", "Berlin", "bridge")


def test_ai_slot_is_freed_even_when_the_ai_fails(monkeypatch):
    monkeypatch.setattr(agent, "llm_call", lambda m, t: (_ for _ in ()).throw(agent.AgentError("boom")))
    for _ in range(agent.AI_SLOTS + 2):  # would hang if slots leaked
        with pytest.raises(agent.AgentError):
            agent.run_passport("x", "Berlin", "bridge")


def test_groq_server_error_is_retried(monkeypatch):
    replies = [FakeResponse(503), FakeResponse(200)]
    calls = []
    monkeypatch.setattr(agent.httpx, "post", lambda *a, **k: calls.append(1) or replies.pop(0))
    assert agent._post_to_groq("m", [], [], "key").status_code == 200
    assert len(calls) == 2


def test_unknown_dial_rejected():
    with pytest.raises(agent.AgentError):
        agent.run_passport("x", "Berlin", "extreme")
