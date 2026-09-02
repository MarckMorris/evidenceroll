from __future__ import annotations

from pathlib import Path

from evidenceroll.simulator import run_benchmark


def test_declared_benchmark_corpus(policy_path: Path) -> None:
    result = run_benchmark(policy_path, batch_size=180)
    assert result["benchmark"] == "synthetic-release-safety-corpus-v1"
    assert result["case_count"] == 4
    assert result["evidenceroll_correct"] == 4
    assert result["http_only_correct"] == 1
    assert "do not measure real-world" in result["disclaimer"]
