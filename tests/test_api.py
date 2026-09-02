from __future__ import annotations

from fastapi.testclient import TestClient

from evidenceroll.app import AppSettings, create_app
from evidenceroll.service import EvidenceRollService


def test_api_lifecycle_and_contract(service: EvidenceRollService) -> None:
    app = create_app(service=service)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        ready = client.get("/readyz")
        assert ready.status_code == 200
        created = client.post(
            "/v1/releases",
            json={
                "release_id": "release-api",
                "champion_version": "champion",
                "challenger_version": "challenger-good",
            },
        )
        assert created.status_code == 201
        prediction_payload = {
            "release_id": "release-api",
            "entity_id": "customer-1",
            "features": {
                "sessions_30d": 8,
                "avg_order_value": 55,
                "days_since_last_order": 21,
                "support_tickets": 2,
                "discount_ratio": 0.25,
            },
        }
        first = client.post(
            "/v1/predictions", json=prediction_payload, headers={"Idempotency-Key": "one"}
        )
        replay = client.post(
            "/v1/predictions", json=prediction_payload, headers={"Idempotency-Key": "one"}
        )
        assert first.status_code == 201
        assert replay.json() == first.json()
        feedback = client.post(
            "/v1/feedback", json={"prediction_id": first.json()["prediction_id"], "label": 1}
        )
        assert feedback.json()["accepted"] is True
        assert client.get("/v1/releases/release-api/evidence").status_code == 200
        assert client.get("/v1/releases/release-api/audit-integrity").json()["valid"] is True
        assert "evidenceroll_predictions_total" in client.get("/metrics").text
        assert client.get("/").status_code == 200
        schema_mismatch = dict(prediction_payload)
        schema_mismatch["features"] = {"sessions_30d": 8}
        mismatch = client.post("/v1/predictions", json=schema_mismatch)
        assert mismatch.status_code == 422
        assert "feature schema mismatch" in mismatch.json()["detail"]


def test_mutations_can_require_api_key(service: EvidenceRollService) -> None:
    settings = AppSettings()
    settings.api_key = "correct-horse"
    app = create_app(service=service, settings=settings)
    with TestClient(app) as client:
        payload = {"release_id": "secure-release"}
        assert client.post("/v1/releases", json=payload).status_code == 401
        assert (
            client.post(
                "/v1/releases",
                json=payload,
                headers={"X-EvidenceRoll-Key": "correct-horse"},
            ).status_code
            == 201
        )


def test_api_validation_and_not_found_are_explicit(service: EvidenceRollService) -> None:
    app = create_app(service=service)
    with TestClient(app) as client:
        assert client.get("/v1/releases/missing").status_code == 404
        invalid = client.post("/v1/feedback", json={"prediction_id": "short", "label": 3})
        assert invalid.status_code == 422
