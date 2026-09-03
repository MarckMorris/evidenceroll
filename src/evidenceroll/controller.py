"""Fail-closed release decision policy and state transitions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from evidenceroll.config import Policy
from evidenceroll.domain import DecisionAction, EvidenceReport, Release, ReleaseStage
from evidenceroll.statistics import EvidenceSnapshot

TERMINAL_STAGES = {ReleaseStage.PROMOTED, ReleaseStage.ROLLED_BACK}


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def decide(release: Release, snapshot: EvidenceSnapshot, policy: Policy) -> EvidenceReport:
    """Turn evidence into one explicit action; missing evidence can never promote."""
    reasons: list[str] = []
    action = DecisionAction.HOLD
    metrics = snapshot.metrics

    if release.stage in TERMINAL_STAGES:
        reasons.append("TERMINAL_RELEASE")
    elif snapshot.prediction_count < policy.evidence.min_predictions:
        reasons.append("INSUFFICIENT_PREDICTIONS")
    elif _metric(metrics, "challenger_p95_latency_ms") > (
        policy.operational_gates.max_challenger_p95_latency_ms
    ):
        reasons.append("CHALLENGER_LATENCY_BREACH")
        action = _unsafe_action(release.stage)
    elif _metric(metrics, "max_feature_psi") > policy.proxy_gates.max_feature_psi:
        reasons.append("FEATURE_DRIFT_BREACH")
        action = _unsafe_action(release.stage)
    elif snapshot.label_count < policy.evidence.min_labels:
        reasons.append("INSUFFICIENT_LABELS")
        if _metric(metrics, "disagreement_rate") > policy.proxy_gates.max_disagreement_rate:
            reasons.append("MODEL_DISAGREEMENT_BREACH")
    elif snapshot.label_coverage < policy.evidence.min_label_coverage:
        reasons.append("INSUFFICIENT_LABEL_COVERAGE")
    elif (missingness := _label_missingness_reason(snapshot, policy)) is not None:
        reasons.append(missingness)
    elif snapshot.evidence_age_seconds is None or (
        snapshot.evidence_age_seconds > policy.evidence.max_age_seconds
    ):
        reasons.append("STALE_EVIDENCE")
    elif metrics.get("accuracy_delta_ci_lower") is None or metrics.get("brier_delta") is None:
        reasons.append("QUALITY_EVIDENCE_UNAVAILABLE")
    elif _metric(metrics, "accuracy_delta_ci_lower") < (
        -policy.quality_gates.non_inferiority_margin
    ):
        reasons.append("ACCURACY_NON_INFERIORITY_FAILED")
        action = DecisionAction.ROLLBACK
    elif _metric(metrics, "brier_delta") > policy.quality_gates.max_brier_regression:
        reasons.append("CALIBRATION_REGRESSION")
        action = DecisionAction.ROLLBACK
    elif _metric(metrics, "disagreement_rate") > policy.proxy_gates.max_disagreement_rate:
        reasons.append("MODEL_DISAGREEMENT_BREACH")
        action = _unsafe_action(release.stage)
    elif release.stage is ReleaseStage.SHADOW:
        reasons.append("SHADOW_EVIDENCE_PASSED")
        action = DecisionAction.START_CANARY
    elif release.stage is ReleaseStage.CANARY:
        reasons.append("CANARY_EVIDENCE_PASSED")
        action = DecisionAction.PROMOTE

    generated_at = datetime.now(timezone.utc).isoformat()
    active_policy_digest = policy_digest(policy)
    digest_payload = {
        "release_id": release.id,
        "stage": release.stage.value,
        "generated_at": generated_at,
        "prediction_count": snapshot.prediction_count,
        "label_count": snapshot.label_count,
        "label_coverage": snapshot.label_coverage,
        "label_coverage_segments": snapshot.label_coverage_segments,
        "latest_prediction_at": snapshot.latest_prediction_at,
        "latest_feedback_at": snapshot.latest_feedback_at,
        "evidence_age_seconds": snapshot.evidence_age_seconds,
        "metrics": metrics,
        "action": action.value,
        "reason_codes": reasons,
        "policy": policy.model_dump(mode="json"),
    }
    return EvidenceReport(
        release_id=release.id,
        stage=release.stage,
        generated_at=generated_at,
        prediction_count=snapshot.prediction_count,
        label_count=snapshot.label_count,
        label_coverage=snapshot.label_coverage,
        label_coverage_segments=snapshot.label_coverage_segments,
        latest_prediction_at=snapshot.latest_prediction_at,
        latest_feedback_at=snapshot.latest_feedback_at,
        evidence_age_seconds=snapshot.evidence_age_seconds,
        metrics=metrics,
        action=action,
        reason_codes=tuple(reasons),
        policy_id=policy.policy_id,
        policy_digest=active_policy_digest,
        evidence_digest=_canonical_digest(digest_payload),
    )


def next_state(
    release: Release,
    action: DecisionAction,
    policy: Policy,
) -> tuple[ReleaseStage, int]:
    if action is DecisionAction.START_CANARY and release.stage is ReleaseStage.SHADOW:
        return ReleaseStage.CANARY, policy.rollout.initial_canary_weight
    if action is DecisionAction.PROMOTE and release.stage is ReleaseStage.CANARY:
        return ReleaseStage.PROMOTED, 100
    if action is DecisionAction.ROLLBACK:
        return ReleaseStage.ROLLED_BACK, 0
    return release.stage, release.canary_weight


def _label_missingness_reason(snapshot: EvidenceSnapshot, policy: Policy) -> str | None:
    """Block when delayed feedback is selective, or when selectiveness cannot be checked.

    A `max_label_coverage_gap` of 1.0 disables the check; any lower value means the window must
    contain at least two readable segments before a paired comparison is trusted.
    """
    threshold = policy.evidence.max_label_coverage_gap
    if threshold >= 1.0:
        return None
    gap = snapshot.metrics.get("max_label_coverage_gap")
    if gap is None or len(snapshot.label_coverage_segments) < 2:
        return "LABEL_MISSINGNESS_UNVERIFIED"
    if gap > threshold:
        return "BIASED_LABEL_MISSINGNESS"
    return None


def _unsafe_action(stage: ReleaseStage) -> DecisionAction:
    return DecisionAction.ROLLBACK if stage is ReleaseStage.CANARY else DecisionAction.HOLD


def _metric(metrics: dict[str, float | None], name: str) -> float:
    """Read a maximum-style gate metric.

    A missing value becomes positive infinity, which breaches every upper bound. Minimum-style
    gates must not use this helper: infinity would satisfy them. Those metrics are checked for
    absence explicitly and reported as `QUALITY_EVIDENCE_UNAVAILABLE`.
    """
    value = metrics.get(name)
    return float(value) if value is not None else float("inf")


def policy_digest(policy: Policy) -> str:
    return _canonical_digest(policy.model_dump(mode="json"))
