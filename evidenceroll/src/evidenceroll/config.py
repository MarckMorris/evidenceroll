"""Policy parsing with fail-closed validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_predictions: int = Field(ge=1)
    min_labels: int = Field(ge=1)
    min_label_coverage: float = Field(gt=0.0, le=1.0)
    max_age_seconds: int = Field(ge=1)

    @model_validator(mode="after")
    def labels_cannot_exceed_predictions(self) -> EvidencePolicy:
        if self.min_labels > self.min_predictions:
            raise ValueError("min_labels cannot exceed min_predictions")
        return self


class ProxyGates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_feature_psi: float = Field(ge=0.0)
    max_disagreement_rate: float = Field(ge=0.0, le=1.0)


class QualityGates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    non_inferiority_margin: float = Field(ge=0.0, le=1.0)
    max_brier_regression: float = Field(ge=0.0, le=1.0)


class OperationalGates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_challenger_p95_latency_ms: float = Field(gt=0.0)


class RolloutPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_canary_weight: int = Field(ge=1, le=99)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=1)
    policy_id: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    evidence: EvidencePolicy
    proxy_gates: ProxyGates
    quality_gates: QualityGates
    operational_gates: OperationalGates
    rollout: RolloutPolicy

    @classmethod
    def from_yaml(cls, path: str | Path) -> Policy:
        source = Path(path)
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("policy document must be a mapping")
        return cls.model_validate(payload)
