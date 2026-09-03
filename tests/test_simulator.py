from __future__ import annotations

from pathlib import Path

from evidenceroll.simulator import SCENARIOS, run_benchmark


def test_declared_benchmark_corpus(policy_path: Path) -> None:
    result = run_benchmark(policy_path, batch_size=180)
    assert result["benchmark"] == "synthetic-release-safety-corpus-v1"
    assert result["case_count"] == len(SCENARIOS)
    assert result["evidenceroll_correct"] == len(SCENARIOS)
    assert result["http_only_correct"] == 1
    assert "do not measure real-world" in result["disclaimer"]


def test_biased_feedback_scenario_is_held_for_missingness(policy_path: Path) -> None:
    result = run_benchmark(policy_path, batch_size=180)
    case = next(c for c in result["cases"] if c["scenario"] == "biased-feedback")
    assert case["final_action"] == "hold"
    assert "BIASED_LABEL_MISSINGNESS" in case["reason_codes"]
