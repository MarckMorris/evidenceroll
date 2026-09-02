from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from evidenceroll.config import Policy


def test_loads_complete_fail_closed_policy(policy_path: Path) -> None:
    policy = Policy.from_yaml(policy_path)
    assert policy.policy_id == "standard-v1"
    assert policy.evidence.min_labels <= policy.evidence.min_predictions
    assert 0 < policy.rollout.initial_canary_weight < 100


def test_unknown_policy_keys_are_rejected(tmp_path: Path, policy_path: Path) -> None:
    content = policy_path.read_text(encoding="utf-8") + "surprise: true\n"
    candidate = tmp_path / "bad.yaml"
    candidate.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError, match="surprise"):
        Policy.from_yaml(candidate)


def test_minimum_labels_cannot_exceed_prediction_floor(policy_path: Path) -> None:
    payload = Policy.from_yaml(policy_path).model_dump()
    payload["evidence"]["min_labels"] = payload["evidence"]["min_predictions"] + 1
    with pytest.raises(ValidationError, match="min_labels"):
        Policy.model_validate(payload)
