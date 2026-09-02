from __future__ import annotations

from pathlib import Path

import pytest

from evidenceroll.acceptance_fixtures import as_feature_dict, generate_churn_batch
from evidenceroll.domain import ReleaseStage
from evidenceroll.schemas import FeatureVector
from evidenceroll.service import EvidenceRollService, PredictionContractError
from evidenceroll.simulator import run_scenario
from evidenceroll.store import IdempotencyConflictError


def test_shadow_predictions_serve_champion_and_store_pair(
    service: EvidenceRollService,
) -> None:
    release = service.create_release("champion", "challenger-good", "release-one")
    features = FeatureVector.model_validate(
        {
            "sessions_30d": 8,
            "avg_order_value": 55,
            "days_since_last_order": 21,
            "support_tickets": 2,
            "discount_ratio": 0.25,
        }
    )
    response = service.predict(release.id, "entity-1", features)
    rows = service.store.observations(release.id, ReleaseStage.SHADOW)
    assert response.served_version == "champion"
    assert response.shadow_evaluated is True
    assert rows[0]["challenger_score"] != rows[0]["champion_score"]


def test_idempotency_replays_same_prediction_but_rejects_key_reuse(
    service: EvidenceRollService,
) -> None:
    release = service.create_release("champion", "challenger-good", "release-one")
    features = FeatureVector.model_validate(
        {
            "sessions_30d": 8,
            "avg_order_value": 55,
            "days_since_last_order": 21,
            "support_tickets": 2,
            "discount_ratio": 0.25,
        }
    )
    first = service.predict(release.id, "entity-1", features, prediction_id="pred-fixed")
    second = service.predict(release.id, "entity-1", features, prediction_id="pred-fixed")
    assert second == first
    with pytest.raises(IdempotencyConflictError):
        service.predict(release.id, "entity-2", features, prediction_id="pred-fixed")


def test_canary_assignment_is_deterministic(service: EvidenceRollService) -> None:
    release = service.create_release("champion", "challenger-good", "release-one")
    canary = service.store.update_release(
        release.id, ReleaseStage.CANARY, 25, "test", expected_revision=release.revision
    )
    outcomes = [service._served_role(canary, "stable-entity") for _ in range(20)]
    assert len(set(outcomes)) == 1


def test_registry_schema_rejects_missing_or_unexpected_features(
    service: EvidenceRollService,
) -> None:
    release = service.create_release("champion", "challenger-good", "release-one")
    incomplete = FeatureVector.model_validate({"sessions_30d": 8.0})
    with pytest.raises(PredictionContractError, match="feature schema mismatch"):
        service.predict(release.id, "entity-1", incomplete)


def test_missing_labels_hold_release(service: EvidenceRollService) -> None:
    release = service.create_release("champion", "challenger-good", "release-one")
    values, _ = generate_churn_batch(130, seed=400)
    for index, row in enumerate(values):
        service.predict(
            release.id,
            f"entity-{index}",
            FeatureVector.model_validate(as_feature_dict(row)),
        )
    report, updated = service.reconcile(release.id)
    assert report.action.value == "hold"
    assert "INSUFFICIENT_LABELS" in report.reason_codes
    assert updated.stage is ReleaseStage.SHADOW


@pytest.mark.integration
@pytest.mark.parametrize(
    ("scenario", "expected_stage"),
    [
        ("healthy", "promoted"),
        ("regressed", "rolled_back"),
        ("missing-feedback", "shadow"),
        ("covariate-shift", "shadow"),
    ],
)
def test_acceptance_scenarios(
    tmp_path: Path,
    policy_path: Path,
    scenario: str,
    expected_stage: str,
) -> None:
    result = run_scenario(scenario, tmp_path / scenario, policy_path, batch_size=180)
    assert result["release"]["stage"] == expected_stage
    assert result["audit_integrity"]["valid"] is True
