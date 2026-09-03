"""Domain types shared by the API, controller, and persistence layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ReleaseStage(str, Enum):
    SHADOW = "shadow"
    CANARY = "canary"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


class DecisionAction(str, Enum):
    HOLD = "hold"
    START_CANARY = "start_canary"
    PROMOTE = "promote"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class Release:
    id: str
    champion_version: str
    challenger_version: str
    stage: ReleaseStage
    canary_weight: int
    created_at: str
    updated_at: str
    last_decision: str | None = None
    revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage"] = self.stage.value
        return data


@dataclass(frozen=True)
class PredictionRecord:
    """One request. The shadow side is null until background scoring completes."""

    id: str
    release_id: str
    entity_id: str
    observed_at: str
    release_stage: ReleaseStage
    features: dict[str, float]
    served_version: str
    champion_score: float | None
    challenger_score: float | None
    champion_prediction: int | None
    challenger_prediction: int | None
    champion_latency_ms: float | None
    challenger_latency_ms: float | None
    request_hash: str
    pending_role: str | None = None
    shadow_error: str | None = None


@dataclass(frozen=True)
class EvidenceReport:
    release_id: str
    stage: ReleaseStage
    generated_at: str
    prediction_count: int
    label_count: int
    label_coverage: float
    label_coverage_segments: dict[str, float]
    latest_prediction_at: str | None
    latest_feedback_at: str | None
    evidence_age_seconds: float | None
    metrics: dict[str, float | None]
    action: DecisionAction
    reason_codes: tuple[str, ...]
    policy_id: str
    policy_digest: str
    evidence_digest: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage"] = self.stage.value
        data["action"] = self.action.value
        data["reason_codes"] = list(self.reason_codes)
        return data
