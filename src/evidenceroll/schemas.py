"""External API contracts."""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class FeatureVector(RootModel[dict[str, float]]):
    """Finite numeric feature map; the active registry enforces its exact schema."""

    @model_validator(mode="before")
    @classmethod
    def validate_raw_map(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("features must be a JSON object")
        if not 1 <= len(value) <= 256:
            raise ValueError("features must contain between 1 and 256 values")
        for name, item in value.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
                raise ValueError(f"invalid feature name: {name!r}")
            if not isinstance(item, int | float) or isinstance(item, bool):
                raise ValueError(f"feature {name} must be a JSON number")
        return value

    @model_validator(mode="after")
    def values_must_be_finite(self) -> FeatureVector:
        for name, value in self.root.items():
            if not math.isfinite(value):
                raise ValueError(f"feature {name} must be finite")
        return self


class CreateReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    champion_version: str = "champion"
    challenger_version: str = "challenger-good"
    release_id: str | None = Field(default=None, min_length=3, max_length=80)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: str = Field(min_length=3, max_length=80)
    entity_id: str = Field(min_length=1, max_length=200)
    features: FeatureVector


class PredictionResponse(BaseModel):
    prediction_id: str
    prediction: int
    probability: float
    served_version: str
    release_stage: str
    shadow_evaluated: bool


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str = Field(min_length=8, max_length=80)
    label: int

    @field_validator("label")
    @classmethod
    def binary_label(cls, value: int) -> int:
        if value not in (0, 1):
            raise ValueError("label must be 0 or 1")
        return value


class FeedbackResponse(BaseModel):
    prediction_id: str
    accepted: bool
    idempotent: bool


class ReleaseResponse(BaseModel):
    id: str
    champion_version: str
    challenger_version: str
    stage: str
    canary_weight: int
    created_at: str
    updated_at: str
    last_decision: str | None
    revision: int


class EvidenceResponse(BaseModel):
    release_id: str
    stage: str
    generated_at: str
    prediction_count: int
    label_count: int
    label_coverage: float
    latest_prediction_at: str | None
    latest_feedback_at: str | None
    evidence_age_seconds: float | None
    metrics: dict[str, float | None]
    action: str
    reason_codes: list[str]
    policy_id: str
    policy_digest: str
    evidence_digest: str


class AuditEventResponse(BaseModel):
    id: int
    release_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    previous_hash: str
    event_hash: str
    hash_algorithm: str


class AuditIntegrityResponse(BaseModel):
    valid: bool
    event_count: int
    failed_event_id: int | None
    last_hash: str
    hash_algorithm: str | None = None
