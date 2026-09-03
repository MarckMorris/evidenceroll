from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from evidenceroll.config import Policy
from evidenceroll.domain import PredictionRecord, ReleaseStage
from evidenceroll.registry import ModelRegistry
from evidenceroll.schemas import FeatureVector
from evidenceroll.service import EvidenceRollService
from evidenceroll.store import SQLiteStore

FEATURES = FeatureVector.model_validate(
    {
        "sessions_30d": 8,
        "avg_order_value": 55,
        "days_since_last_order": 21,
        "support_tickets": 2,
        "discount_ratio": 0.25,
    }
)


@pytest.fixture()
def background_service(
    tmp_path: Path, registry_path: Path, policy_path: Path
) -> Iterator[EvidenceRollService]:
    service = EvidenceRollService(
        SQLiteStore(tmp_path / "events.db"),
        ModelRegistry(registry_path),
        Policy.from_yaml(policy_path),
        shadow_scoring="background",
        shadow_workers=2,
    )
    yield service
    service.close()


def test_background_mode_rejects_unknown_setting(
    tmp_path: Path, registry_path: Path, policy_path: Path
) -> None:
    with pytest.raises(ValueError, match="shadow_scoring"):
        EvidenceRollService(
            SQLiteStore(tmp_path / "events.db"),
            ModelRegistry(registry_path),
            Policy.from_yaml(policy_path),
            shadow_scoring="whenever",
        )


def test_shadow_model_is_scored_outside_the_response_path(
    background_service: EvidenceRollService,
) -> None:
    """The caller gets the champion answer; the challenger is completed afterwards."""
    release = background_service.create_release("champion", "challenger-good", "release-one")
    response = background_service.predict(release.id, "entity-1", FEATURES)

    assert response.served_version == "champion"
    assert background_service.flush_shadow(timeout=30.0) is True

    stored = background_service.store.get_prediction(response.prediction_id)
    assert stored is not None
    assert stored["pending_role"] is None
    assert stored["champion_score"] is not None
    assert stored["challenger_score"] is not None
    assert stored["challenger_latency_ms"] is not None


def test_incomplete_pairs_are_not_evidence(service: EvidenceRollService) -> None:
    """A half-scored request counts as neither evidence for nor against the release."""
    release = service.create_release("champion", "challenger-good", "release-one")
    service.store.add_prediction(
        PredictionRecord(
            id="pred-pending",
            release_id=release.id,
            entity_id="customer-1",
            observed_at="2026-09-02T12:00:00+00:00",
            release_stage=ReleaseStage.SHADOW,
            features=dict(FEATURES.root),
            served_version="champion",
            champion_score=0.4,
            challenger_score=None,
            champion_prediction=0,
            challenger_prediction=None,
            champion_latency_ms=1.0,
            challenger_latency_ms=None,
            request_hash="hash-pending",
            pending_role="challenger",
        )
    )
    assert service.store.incomplete_prediction_counts(release.id) == {"pending": 1, "failed": 0}
    assert service.store.observations(release.id, ReleaseStage.SHADOW) == []

    service.store.fail_shadow_score("pred-pending", "endpoint unavailable")
    assert service.store.incomplete_prediction_counts(release.id) == {"pending": 0, "failed": 1}
    report = service.evaluate(release.id)
    assert report.prediction_count == 0
    assert "INSUFFICIENT_PREDICTIONS" in report.reason_codes


def test_failed_shadow_scoring_abandons_the_pair(
    background_service: EvidenceRollService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = background_service.create_release("champion", "challenger-good", "release-one")
    original = background_service.gateway.score

    def failing(version: str, values: np.ndarray) -> float:
        if version == "challenger-good":
            raise RuntimeError("challenger endpoint refused the connection")
        return float(original(version, values))

    monkeypatch.setattr(background_service.gateway, "score", failing)
    response = background_service.predict(release.id, "entity-1", FEATURES)
    assert background_service.flush_shadow(timeout=30.0) is True

    stored = background_service.store.get_prediction(response.prediction_id)
    assert stored is not None
    assert stored["shadow_error"].startswith("RuntimeError")
    assert stored["champion_score"] is not None
    assert stored["challenger_score"] is None
    assert background_service.store.observations(release.id, ReleaseStage.SHADOW) == []


def test_completing_an_unknown_pending_pair_is_refused(
    background_service: EvidenceRollService,
) -> None:
    with pytest.raises(ValueError, match="unknown scoring role"):
        background_service.store.complete_shadow_score("pred-x", "oracle", 0.5, 1, 1.0)


def test_inline_mode_stores_a_complete_pair(service: EvidenceRollService) -> None:
    release = service.create_release("champion", "challenger-good", "release-one")
    response = service.predict(release.id, "entity-1", FEATURES)
    stored = service.store.get_prediction(response.prediction_id)

    assert service.flush_shadow() is True
    assert stored is not None
    assert stored["pending_role"] is None
    assert stored["challenger_score"] is not None
