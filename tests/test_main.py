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


def test_health_has_no_key_values(monkeypatch):
    monkeypatch.setenv("QLOO_API_KEY", "secret-qloo-value")
    monkeypatch.setenv("LLM_API_KEY", "secret-llm-value")
    data = client.get("/api/health").json()
    assert data["qloo_key_configured"] is True
    assert data["llm_key_configured"] is True
    assert "secret" not in str(data)
