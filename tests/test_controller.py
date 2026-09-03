from __future__ import annotations

from pathlib import Path

import pytest

from evidenceroll.config import Policy
from evidenceroll.controller import decide, next_state, policy_digest
from evidenceroll.domain import DecisionAction, Release, ReleaseStage
from evidenceroll.statistics import EvidenceSnapshot


def release(stage: ReleaseStage = ReleaseStage.SHADOW) -> Release:
    return Release(
        id="release-one",
        champion_version="champion",
        challenger_version="challenger",
        stage=stage,
        canary_weight=10 if stage is ReleaseStage.CANARY else 0,
        created_at="2026-09-02T00:00:00+00:00",
        updated_at="2026-09-02T00:00:00+00:00",
    )


def snapshot(**overrides: object) -> EvidenceSnapshot:
    metrics: dict[str, float | None] = {
        "challenger_p95_latency_ms": 10.0,
        "max_feature_psi": 0.1,
        "disagreement_rate": 0.1,
        "accuracy_delta_ci_lower": -0.01,
        "brier_delta": -0.01,
        "max_label_coverage_gap": 0.02,
    }
    metrics.update(overrides.pop("metrics", {}))  # type: ignore[arg-type]
    values = {
        "prediction_count": 150,
        "label_count": 120,
        "label_coverage": 0.8,
        "label_coverage_segments": {"served_role:champion": 0.81, "served_role:challenger": 0.79},
        "latest_prediction_at": "2026-09-02T00:00:00+00:00",
        "latest_feedback_at": "2026-09-02T00:00:05+00:00",
        "evidence_age_seconds": 10.0,
        "metrics": metrics,
    }
    values.update(overrides)
    return EvidenceSnapshot(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "reason", "action"),
    [
        ({"prediction_count": 10}, "INSUFFICIENT_PREDICTIONS", DecisionAction.HOLD),
        ({"evidence_age_seconds": 90_000.0}, "STALE_EVIDENCE", DecisionAction.HOLD),
        (
            {"metrics": {"challenger_p95_latency_ms": 100.0}},
            "CHALLENGER_LATENCY_BREACH",
            DecisionAction.HOLD,
        ),
        (
            {"metrics": {"max_feature_psi": 1.0}},
            "FEATURE_DRIFT_BREACH",
            DecisionAction.HOLD,
        ),
        ({"label_count": 2}, "INSUFFICIENT_LABELS", DecisionAction.HOLD),
        ({"label_coverage": 0.2}, "INSUFFICIENT_LABEL_COVERAGE", DecisionAction.HOLD),
        (
            {"metrics": {"accuracy_delta_ci_lower": -0.5}},
            "ACCURACY_NON_INFERIORITY_FAILED",
            DecisionAction.ROLLBACK,
        ),
        (
            {"metrics": {"brier_delta": 0.5}},
            "CALIBRATION_REGRESSION",
            DecisionAction.ROLLBACK,
        ),
        (
            {"metrics": {"disagreement_rate": 0.9}},
            "MODEL_DISAGREEMENT_BREACH",
            DecisionAction.HOLD,
        ),
        (
            {"metrics": {"max_label_coverage_gap": 0.6}},
            "BIASED_LABEL_MISSINGNESS",
            DecisionAction.HOLD,
        ),
        (
            {"label_coverage_segments": {"served_role:champion": 0.8}},
            "LABEL_MISSINGNESS_UNVERIFIED",
            DecisionAction.HOLD,
        ),
        (
            {"metrics": {"accuracy_delta_ci_lower": None}},
            "QUALITY_EVIDENCE_UNAVAILABLE",
            DecisionAction.HOLD,
        ),
        (
            {"metrics": {"brier_delta": None}},
            "QUALITY_EVIDENCE_UNAVAILABLE",
            DecisionAction.HOLD,
        ),
    ],
)
def test_fail_closed_policy_branches(
    policy_path: Path,
    change: dict[str, object],
    reason: str,
    action: DecisionAction,
) -> None:
    report = decide(release(), snapshot(**change), Policy.from_yaml(policy_path))
    assert report.action is action
    assert reason in report.reason_codes


@pytest.mark.parametrize("absent", ["accuracy_delta_ci_lower", "brier_delta"])
def test_missing_quality_metric_can_never_promote(policy_path: Path, absent: str) -> None:
    """A minimum-style gate must block when its metric is absent, not pass by default."""
    for stage in (ReleaseStage.SHADOW, ReleaseStage.CANARY):
        report = decide(
            release(stage),
            snapshot(metrics={absent: None}),
            Policy.from_yaml(policy_path),
        )
        assert report.action is DecisionAction.HOLD
        assert "QUALITY_EVIDENCE_UNAVAILABLE" in report.reason_codes


def test_selective_feedback_blocks_promotion(policy_path: Path) -> None:
    """Labels that arrive for one cohort and not the other measure missingness, not quality."""
    report = decide(
        release(ReleaseStage.CANARY),
        snapshot(
            label_coverage_segments={
                "served_role:champion": 0.95,
                "served_role:challenger": 0.40,
            },
            metrics={"max_label_coverage_gap": 0.55},
        ),
        Policy.from_yaml(policy_path),
    )
    assert report.action is DecisionAction.HOLD
    assert "BIASED_LABEL_MISSINGNESS" in report.reason_codes


def test_missingness_check_can_be_disabled_explicitly(policy_path: Path) -> None:
    payload = Policy.from_yaml(policy_path).model_dump()
    payload["evidence"]["max_label_coverage_gap"] = 1.0
    disabled = Policy.model_validate(payload)
    report = decide(
        release(),
        snapshot(label_coverage_segments={}, metrics={"max_label_coverage_gap": None}),
        disabled,
    )
    assert report.action is DecisionAction.START_CANARY


def test_canary_proxy_breach_rolls_back(policy_path: Path) -> None:
    report = decide(
        release(ReleaseStage.CANARY),
        snapshot(metrics={"max_feature_psi": 1.0}),
        Policy.from_yaml(policy_path),
    )
    assert report.action is DecisionAction.ROLLBACK


def test_terminal_release_cannot_transition(policy_path: Path) -> None:
    active_policy = Policy.from_yaml(policy_path)
    report = decide(release(ReleaseStage.PROMOTED), snapshot(), active_policy)
    assert report.action is DecisionAction.HOLD
    assert report.reason_codes == ("TERMINAL_RELEASE",)
    assert next_state(release(ReleaseStage.PROMOTED), report.action, active_policy) == (
        ReleaseStage.PROMOTED,
        0,
    )


def test_policy_digest_changes_with_material_threshold(policy_path: Path) -> None:
    active = Policy.from_yaml(policy_path)
    payload = active.model_dump()
    payload["proxy_gates"]["max_feature_psi"] = 0.2
    changed = Policy.model_validate(payload)
    assert policy_digest(active) != policy_digest(changed)
