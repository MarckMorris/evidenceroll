from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from evidenceroll.statistics import (
    calculate_evidence,
    label_coverage_by_segment,
    label_coverage_gap,
    paired_accuracy_interval,
    population_stability_index,
)


def test_psi_is_near_zero_for_matching_histogram() -> None:
    values = np.asarray([0.1, 0.2, 1.1, 1.2])
    psi = population_stability_index(values, [1.0], [0.5, 0.5])
    assert psi == pytest.approx(0.0)


def test_psi_detects_large_shift() -> None:
    values = np.asarray([10.0] * 100)
    psi = population_stability_index(values, [1.0], [0.9, 0.1])
    assert psi > 1.0


def test_paired_accuracy_interval_is_directional() -> None:
    champion = np.asarray([True, False, False, True, False] * 20)
    challenger = np.asarray([True, True, True, True, True] * 20)
    mean, lower, upper = paired_accuracy_interval(champion, challenger)
    assert lower > 0
    assert lower <= mean <= upper


def test_empty_evidence_is_explicit() -> None:
    snapshot = calculate_evidence([], {}, now=datetime.now(timezone.utc))
    assert snapshot.prediction_count == 0
    assert snapshot.label_count == 0
    assert snapshot.evidence_age_seconds is None


def test_evidence_freshness_uses_feedback_time_not_prediction_time() -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    row = {
        "observed_at": "2026-09-02T11:59:59+00:00",
        "feedback_at": "2026-09-01T12:00:00+00:00",
        "label": 1,
        "features": {"feature": 0.5},
        "champion_score": 0.8,
        "challenger_score": 0.9,
        "champion_prediction": 1,
        "challenger_prediction": 1,
        "champion_latency_ms": 1.0,
        "challenger_latency_ms": 1.0,
    }
    profile = {"feature": {"cut_points": [0.4], "proportions": [0.5, 0.5]}}
    snapshot = calculate_evidence([row], profile, now=now)
    assert snapshot.latest_prediction_at == "2026-09-02T11:59:59+00:00"
    assert snapshot.latest_feedback_at == "2026-09-01T12:00:00+00:00"
    assert snapshot.evidence_age_seconds == 86_400.0


def test_invalid_paired_arrays_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        paired_accuracy_interval(np.asarray([]), np.asarray([]))


def test_label_coverage_by_segment_detects_selective_feedback() -> None:
    profile = {"x": {"cut_points": [1.0], "proportions": [0.5, 0.5]}}
    observations = [
        {
            "features": {"x": 0.5 if index % 2 == 0 else 1.5},
            "champion_prediction": index % 2,
            "challenger_prediction": index % 2,
            "served_version": "champion" if index % 2 == 0 else "challenger",
            "label": 1 if index % 2 == 0 else None,
        }
        for index in range(80)
    ]
    segments = label_coverage_by_segment(
        observations,
        profile,
        champion_version="champion",
        min_segment_predictions=30,
    )
    assert segments["served_role:champion"] == pytest.approx(1.0)
    assert segments["served_role:challenger"] == pytest.approx(0.0)
    assert label_coverage_gap(segments) == pytest.approx(1.0)


def test_label_coverage_gap_is_undecidable_below_two_readable_segments() -> None:
    assert label_coverage_gap({}) is None
    assert label_coverage_gap({"served_role:champion": 0.9}) is None


def test_small_segments_are_not_reported() -> None:
    observations = [
        {
            "features": {},
            "champion_prediction": 1,
            "served_version": "champion",
            "label": None,
        }
        for _ in range(5)
    ]
    assert label_coverage_by_segment(observations, {}, min_segment_predictions=30) == {}
