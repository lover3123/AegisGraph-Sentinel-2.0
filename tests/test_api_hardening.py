"""Regression tests for production-readiness hardening."""

from pathlib import Path
from unittest.mock import Mock

import pytest

import src.api.main as api_main
from src.api.main import state


def _transaction(transaction_id="txn_001", amount=100.0):
    return {
        "transaction_id": transaction_id,
        "source_account": "acct_src",
        "target_account": "acct_dst",
        "amount": amount,
        "currency": "INR",
        "mode": "UPI",
        "timestamp": "2026-02-26T14:30:00Z",
    }


def test_health_smoke(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_stats_smoke(api_client):
    response = api_client.get("/stats")
    assert response.status_code == 200
    assert "total_requests" in response.json()


def test_missing_amount_returns_json_validation_error(api_client):
    payload = _transaction()
    payload.pop("amount")

    response = api_client.post("/api/v1/fraud/check", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "validation_errors" in body["error"]["details"]


def test_invalid_payload_returns_json_validation_error(api_client):
    response = api_client.post("/api/v1/fraud/check", json={"amount": "bad"})

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "ValidationException"


def test_batch_overflow_rejected(api_client):
    transactions = [_transaction(f"txn_{i}") for i in range(101)]

    response = api_client.post("/api/v1/fraud/batch", json={"transactions": transactions})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_graph_artifact_does_not_crash(api_client):
    assert not Path("data/synthetic/graph.graphml").exists()
    assert not Path("data/synthetic/graph.gpickle").exists()

    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["graph_loaded"] is False
    assert state.graph_loaded is False


def test_validation_error_payload_is_json_safe(api_client):
    payload = _transaction()
    payload["amount"] = -1

    response = api_client.post("/api/v1/fraud/check", json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["details"]["validation_errors"]


def test_lateral_movement_initializes_even_when_other_innovations_are_unavailable(monkeypatch):
    dummy_detector = object()
    startup_logger = Mock()
    register_service = Mock()

    monkeypatch.setattr(api_main, "INNOVATIONS_AVAILABLE", False)
    monkeypatch.setattr(api_main, "LATERAL_MOVEMENT_AVAILABLE", True)
    monkeypatch.setattr(api_main, "LateralMovementDetector", lambda: dummy_detector)
    monkeypatch.setattr(api_main.state.services, "register_service", register_service)
    monkeypatch.setattr(api_main.state, "lateral_movement_detector", None, raising=False)

    api_main._initialize_innovation_runtime(startup_logger)

    assert api_main.state.lateral_movement_detector is dummy_detector
    register_service.assert_called_once_with("lateral_movement_detector", dummy_detector, replace=True)


@pytest.mark.parametrize(
    "base_score,lateral_boost,expected_decision",
    [
        (0.25, 0.35, "REVIEW"),
        (0.45, 0.35, "BLOCK"),
    ],
)
def test_scoring_applies_lateral_movement_even_when_innovations_flag_is_false(
    monkeypatch,
    base_score,
    lateral_boost,
    expected_decision,
):
    detector = Mock()
    detector.analyze_account.return_value = (lateral_boost, True)

    monkeypatch.setattr(
        api_main,
        "compute_risk_score",
        lambda transaction, biometrics=None, **kwargs: {
            "risk_score": base_score,
            "decision": "ALLOW",
            "confidence": 0.85,
            "breakdown": {"graph": 0.0, "velocity": 0.0, "behavior": 0.0, "entropy": 0.0},
        },
    )

    result = api_main._run_scoring_pipeline(
        transaction={"transaction_id": "txn_lateral_001"},
        biometrics=None,
        source_account="acct_src",
        target_account="acct_dst",
        lateral_detector=detector,
        innovations_available=False,
    )

    detector.update_graph.assert_called_once_with("acct_src", "acct_dst")
    detector.analyze_account.assert_called_once_with("acct_src")
    assert result["risk_score"] == pytest.approx(min(1.0, base_score + lateral_boost))
    assert result["breakdown"]["lateral_movement"] == lateral_boost
    assert result["lateral_movement_detected"] is True
    assert result["decision"] == expected_decision


def test_scoring_continues_when_lateral_detector_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "compute_risk_score",
        lambda transaction, biometrics=None, **kwargs: {
            "risk_score": 0.2,
            "decision": "ALLOW",
            "confidence": 0.85,
            "breakdown": {"graph": 0.0, "velocity": 0.0, "behavior": 0.0, "entropy": 0.0},
        },
    )

    result = api_main._run_scoring_pipeline(
        transaction={"transaction_id": "txn_lateral_none"},
        biometrics=None,
        source_account="acct_src",
        target_account="acct_dst",
        lateral_detector=None,
        innovations_available=False,
    )

    assert result["risk_score"] == pytest.approx(0.2)
    assert result["decision"] == "ALLOW"
    assert "lateral_movement" not in result["breakdown"]


def test_scoring_recovers_when_lateral_analysis_raises(monkeypatch):
    class RaisingDetector:
        def update_graph(self, source_account, target_account):
            raise RuntimeError("centrality backend unavailable")

        def analyze_account(self, source_account):
            raise RuntimeError("should not be reached")

    monkeypatch.setattr(
        api_main,
        "compute_risk_score",
        lambda transaction, biometrics=None, **kwargs: {
            "risk_score": 0.33,
            "decision": "ALLOW",
            "confidence": 0.85,
            "breakdown": {"graph": 0.0, "velocity": 0.0, "behavior": 0.0, "entropy": 0.0},
        },
    )

    result = api_main._run_scoring_pipeline(
        transaction={"transaction_id": "txn_lateral_error"},
        biometrics=None,
        source_account="acct_src",
        target_account="acct_dst",
        lateral_detector=RaisingDetector(),
        innovations_available=False,
    )

    assert result["risk_score"] == pytest.approx(0.33)
    assert result["decision"] == "ALLOW"
    assert "lateral_movement" not in result["breakdown"]
