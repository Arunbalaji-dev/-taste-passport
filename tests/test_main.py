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

    def boom(*args):
        raise AgentError("The AI model is busy right now.")

    monkeypatch.setattr(main, "run_passport", boom)
    response = client.post("/api/passport", json={"favourites": "Interstellar", "city": "Berlin"})
    assert response.status_code == 502
    assert response.json() == {"error": "The AI model is busy right now."}


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
