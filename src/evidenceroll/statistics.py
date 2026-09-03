"""Model-change evidence calculated from paired predictions and delayed labels."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score


@dataclass(frozen=True)
class EvidenceSnapshot:
    prediction_count: int
    label_count: int
    label_coverage: float
    label_coverage_segments: dict[str, float]
    latest_prediction_at: str | None
    latest_feedback_at: str | None
    evidence_age_seconds: float | None
    metrics: dict[str, float | None]


def population_stability_index(
    values: np.ndarray,
    cut_points: list[float],
    reference_proportions: list[float],
    epsilon: float = 1e-6,
) -> float:
    """Compute PSI against a fixed training profile.

    PSI is a distribution warning signal. It does not prove concept drift.
    """
    if values.size == 0:
        return 0.0
    bins = np.asarray([-np.inf, *cut_points, np.inf], dtype=float)
    counts, _ = np.histogram(values.astype(float), bins=bins)
    actual = counts.astype(float) / max(float(counts.sum()), 1.0)
    expected = np.asarray(reference_proportions, dtype=float)
    if actual.shape != expected.shape:
        raise ValueError("reference profile and observed histogram have different shapes")
    actual = np.clip(actual, epsilon, None)
    expected = np.clip(expected, epsilon, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def paired_accuracy_interval(
    champion_correct: np.ndarray,
    challenger_correct: np.ndarray,
    confidence_z: float = 1.96,
) -> tuple[float, float, float]:
    """Approximate paired confidence interval for challenger-minus-champion accuracy."""
    if champion_correct.size == 0 or champion_correct.size != challenger_correct.size:
        raise ValueError("paired correctness arrays must be non-empty and equally sized")
    deltas = challenger_correct.astype(float) - champion_correct.astype(float)
    mean = float(np.mean(deltas))
    if deltas.size == 1:
        return mean, mean, mean
    standard_error = float(np.std(deltas, ddof=1) / math.sqrt(deltas.size))
    lower = max(-1.0, mean - confidence_z * standard_error)
    upper = min(1.0, mean + confidence_z * standard_error)
    return mean, lower, upper


def label_coverage_by_segment(
    observations: list[dict[str, Any]],
    reference_profile: dict[str, dict[str, list[float]]],
    champion_version: str | None = None,
    min_segment_predictions: int = 30,
) -> dict[str, float]:
    """Label coverage per comparable slice of the same evidence window.

    Aggregate coverage hides selective feedback: labels can arrive for the champion cohort and
    not the challenger one, or only for predicted positives. A paired comparison built on that
    window measures the missingness, not the release delta. Only segments with enough
    predictions to be readable are returned.
    """
    totals: dict[str, int] = {}
    labeled: dict[str, int] = {}
    for row in observations:
        keys = _segment_keys(row, reference_profile, champion_version)
        has_label = row.get("label") is not None
        for key in keys:
            totals[key] = totals.get(key, 0) + 1
            if has_label:
                labeled[key] = labeled.get(key, 0) + 1
    return {
        key: labeled.get(key, 0) / total
        for key, total in sorted(totals.items())
        if total >= min_segment_predictions
    }


def label_coverage_gap(segments: dict[str, float]) -> float | None:
    """Widest coverage difference between two readable segments, or None when undecidable."""
    if len(segments) < 2:
        return None
    return max(segments.values()) - min(segments.values())


def _segment_keys(
    row: dict[str, Any],
    reference_profile: dict[str, dict[str, list[float]]],
    champion_version: str | None,
) -> list[str]:
    keys: list[str] = []
    champion_prediction = row.get("champion_prediction")
    if champion_prediction is not None:
        keys.append(f"predicted_class:{int(champion_prediction)}")
    if champion_version is not None:
        role = "champion" if row.get("served_version") == champion_version else "challenger"
        keys.append(f"served_role:{role}")
    features = row.get("features") or {}
    for feature, profile in reference_profile.items():
        if feature not in features:
            continue
        cut_points = np.asarray(profile["cut_points"], dtype=float)
        index = int(np.searchsorted(cut_points, float(features[feature]), side="right"))
        keys.append(f"feature:{feature}:bin{index}")
    return keys


def _safe_auc(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    if np.unique(labels).size < 2:
        return None
    return float(roc_auc_score(labels, probabilities))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def calculate_evidence(
    observations: list[dict[str, Any]],
    reference_profile: dict[str, dict[str, list[float]]],
    now: datetime | None = None,
    champion_version: str | None = None,
    min_segment_predictions: int = 30,
) -> EvidenceSnapshot:
    now_utc = now or datetime.now(timezone.utc)
    count = len(observations)
    labeled = [row for row in observations if row["label"] is not None]
    label_count = len(labeled)
    coverage = label_count / count if count else 0.0

    latest_prediction_at = (
        max(_parse_time(str(row["observed_at"])) for row in observations).isoformat()
        if count
        else None
    )
    latest_feedback = (
        max(_parse_time(str(row["feedback_at"])) for row in labeled) if labeled else None
    )
    latest_feedback_at = latest_feedback.isoformat() if latest_feedback else None
    age = max(0.0, (now_utc - latest_feedback).total_seconds()) if latest_feedback else None
    segments = label_coverage_by_segment(
        observations,
        reference_profile,
        champion_version=champion_version,
        min_segment_predictions=min_segment_predictions,
    )

    metrics: dict[str, float | None] = {
        "max_label_coverage_gap": label_coverage_gap(segments),
        "max_feature_psi": None,
        "mean_feature_psi": None,
        "disagreement_rate": None,
        "champion_mean_confidence": None,
        "challenger_mean_confidence": None,
        "confidence_delta": None,
        "champion_p95_latency_ms": None,
        "challenger_p95_latency_ms": None,
        "champion_accuracy": None,
        "challenger_accuracy": None,
        "accuracy_delta": None,
        "accuracy_delta_ci_lower": None,
        "accuracy_delta_ci_upper": None,
        "champion_brier": None,
        "challenger_brier": None,
        "brier_delta": None,
        "champion_roc_auc": None,
        "challenger_roc_auc": None,
    }
    if not observations:
        return EvidenceSnapshot(
            count,
            label_count,
            coverage,
            segments,
            latest_prediction_at,
            latest_feedback_at,
            age,
            metrics,
        )

    champion_scores = np.asarray([row["champion_score"] for row in observations], dtype=float)
    challenger_scores = np.asarray([row["challenger_score"] for row in observations], dtype=float)
    champion_predictions = np.asarray(
        [row["champion_prediction"] for row in observations], dtype=int
    )
    challenger_predictions = np.asarray(
        [row["challenger_prediction"] for row in observations], dtype=int
    )
    champion_confidence = np.maximum(champion_scores, 1.0 - champion_scores)
    challenger_confidence = np.maximum(challenger_scores, 1.0 - challenger_scores)

    psi_values: list[float] = []
    for feature, profile in reference_profile.items():
        feature_values = np.asarray([row["features"][feature] for row in observations], dtype=float)
        psi_values.append(
            population_stability_index(
                feature_values,
                profile["cut_points"],
                profile["proportions"],
            )
        )
    metrics.update(
        {
            "max_feature_psi": float(max(psi_values)),
            "mean_feature_psi": float(np.mean(psi_values)),
            "disagreement_rate": float(np.mean(champion_predictions != challenger_predictions)),
            "champion_mean_confidence": float(np.mean(champion_confidence)),
            "challenger_mean_confidence": float(np.mean(challenger_confidence)),
            "confidence_delta": float(np.mean(challenger_confidence - champion_confidence)),
            "champion_p95_latency_ms": float(
                np.percentile([row["champion_latency_ms"] for row in observations], 95)
            ),
            "challenger_p95_latency_ms": float(
                np.percentile([row["challenger_latency_ms"] for row in observations], 95)
            ),
        }
    )

    if labeled:
        labels = np.asarray([row["label"] for row in labeled], dtype=int)
        champion_labeled_scores = np.asarray(
            [row["champion_score"] for row in labeled], dtype=float
        )
        challenger_labeled_scores = np.asarray(
            [row["challenger_score"] for row in labeled], dtype=float
        )
        champion_labeled_predictions = np.asarray(
            [row["champion_prediction"] for row in labeled], dtype=int
        )
        challenger_labeled_predictions = np.asarray(
            [row["challenger_prediction"] for row in labeled], dtype=int
        )
        champion_correct = champion_labeled_predictions == labels
        challenger_correct = challenger_labeled_predictions == labels
        delta, lower, upper = paired_accuracy_interval(champion_correct, challenger_correct)
        champion_brier = float(brier_score_loss(labels, champion_labeled_scores))
        challenger_brier = float(brier_score_loss(labels, challenger_labeled_scores))
        metrics.update(
            {
                "champion_accuracy": float(accuracy_score(labels, champion_labeled_predictions)),
                "challenger_accuracy": float(
                    accuracy_score(labels, challenger_labeled_predictions)
                ),
                "accuracy_delta": delta,
                "accuracy_delta_ci_lower": lower,
                "accuracy_delta_ci_upper": upper,
                "champion_brier": champion_brier,
                "challenger_brier": challenger_brier,
                "brier_delta": challenger_brier - champion_brier,
                "champion_roc_auc": _safe_auc(labels, champion_labeled_scores),
                "challenger_roc_auc": _safe_auc(labels, challenger_labeled_scores),
            }
        )
    return EvidenceSnapshot(
        count,
        label_count,
        coverage,
        segments,
        latest_prediction_at,
        latest_feedback_at,
        age,
        metrics,
    )
