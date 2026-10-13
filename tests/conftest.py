import pytest

from app import agent, main, qloo


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Every test starts with empty caches, no rate-limit history and no waiting."""
    qloo.clear_cache()
    agent._result_cache.clear()
    main._recent.clear()
    monkeypatch.setattr(qloo, "RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(agent, "RETRY_DELAY_SECONDS", 0)
    yield
