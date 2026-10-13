from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_home_page_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Taste Passport" in response.text


def test_passport_returns_friendly_error_when_agent_fails(monkeypatch):
    from app import main
    from app.agent import AgentError

    def boom(*args, **kwargs):
        raise AgentError("The AI model is busy right now.")

    monkeypatch.setattr(main, "run_passport", boom)
    response = client.post("/api/passport", json={"favourites": "Interstellar", "city": "Berlin"})
    assert response.status_code == 502
    assert response.json() == {"error": "The AI model is busy right now."}


def test_unexpected_error_gives_friendly_message_not_a_crash(monkeypatch):
    from app import main

    def bug(*args, **kwargs):
        raise ValueError("internal detail that users must not see")

    monkeypatch.setattr(main, "run_passport", bug)
    response = client.post("/api/passport", json={"favourites": "Interstellar", "city": "Berlin"})
    assert response.status_code == 500
    assert "internal detail" not in response.text
    assert "try again" in response.json()["error"]


def test_rate_limit_blocks_a_flood_from_one_visitor(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "run_passport", lambda *a, **k: {"ok": True})
    body = {"favourites": "Interstellar", "city": "Berlin"}
    statuses = [client.post("/api/passport", json=body).status_code for _ in range(main.RATE_LIMIT + 2)]
    assert statuses[:main.RATE_LIMIT] == [200] * main.RATE_LIMIT
    assert statuses[-1] == 429
    # a different visitor is not affected
    other = client.post("/api/passport", json=body, headers={"x-forwarded-for": "9.9.9.9"})
    assert other.status_code == 200


def test_passport_rejects_empty_input():
    response = client.post("/api/passport", json={"favourites": "", "city": "Berlin"})
    assert response.status_code == 422


def test_health_has_no_key_values(monkeypatch):
    monkeypatch.setenv("QLOO_API_KEY", "secret-qloo-value")
    monkeypatch.setenv("LLM_API_KEY", "secret-llm-value")
    data = client.get("/api/health").json()
    assert data["qloo_key_configured"] is True
    assert data["llm_key_configured"] is True
    assert "secret" not in str(data)
