"""Shared pytest fixtures for API tests."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def api_client(monkeypatch):
    """FastAPI client that runs lifespan without opening a real socket."""
    monkeypatch.setenv("AEGIS_ENV", "test")
    with TestClient(app) as client:
        yield client
    from src.api.main import state

    state.voice_analyzer = None
    state.mule_scorer = None
    state.honeypot_manager = None
    state.blockchain_manager = None
    state.aegis_oracle = None
