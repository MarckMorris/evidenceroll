"""Application service: routing, paired inference, feedback, and reconciliation."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from evidenceroll.adapters import ModelGateway
from evidenceroll.config import Policy
from evidenceroll.controller import decide, next_state
from evidenceroll.domain import EvidenceReport, PredictionRecord, Release, ReleaseStage
from evidenceroll.registry import ModelRegistry, RegistryError
from evidenceroll.schemas import FeatureVector, PredictionResponse
from evidenceroll.statistics import calculate_evidence
from evidenceroll.store import IdempotencyConflictError, SQLiteStore, utc_now
from evidenceroll.telemetry import Telemetry

LOGGER = logging.getLogger(__name__)

SHADOW_SCORING_MODES = ("inline", "background")


class PredictionContractError(ValueError):
    """A prediction violates the active model or feature contract."""


class EvidenceRollService:
    def __init__(
        self,
        store: SQLiteStore,
        registry: ModelRegistry,
        policy: Policy,
        telemetry: Telemetry | None = None,
        shadow_scoring: str = "inline",
        shadow_workers: int = 2,
    ) -> None:
        if shadow_scoring not in SHADOW_SCORING_MODES:
            raise ValueError(f"shadow_scoring must be one of {SHADOW_SCORING_MODES}")
        self.store = store
        self.registry = registry
        self.policy = policy
        self.telemetry = telemetry or Telemetry()
        self.gateway = ModelGateway(registry)
        self.shadow_scoring = shadow_scoring
        self._shadow_pool: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=shadow_workers, thread_name_prefix="evidenceroll-shadow")
            if shadow_scoring == "background"
            else None
        )
        self._shadow_futures: set[Future[None]] = set()

    def flush_shadow(self, timeout: float = 30.0) -> bool:
        """Wait for in-flight background scoring. Returns False when work is still running."""
        if self._shadow_pool is None:
            return True
        pending = set(self._shadow_futures)
        if not pending:
            return True
        _, not_done = wait(pending, timeout=timeout)
        return not not_done

    def close(self) -> None:
        if self._shadow_pool is not None:
            self._shadow_pool.shutdown(wait=True)
            self._shadow_pool = None

    @classmethod
    def from_paths(
        cls,
        database_path: str | Path,
        registry_path: str | Path,
        policy_path: str | Path,
    ) -> EvidenceRollService:
        return cls(
            store=SQLiteStore(database_path),
            registry=ModelRegistry(registry_path),
            policy=Policy.from_yaml(policy_path),
        )

    def create_release(
        self,
        champion_version: str,
        challenger_version: str,
        release_id: str | None = None,
    ) -> Release:
        if not self.registry.ready:
            raise RegistryError(
                "registry is not release-ready; register model endpoints and profile every feature"
            )
        self.registry.verify(champion_version)
        self.registry.verify(challenger_version)
        release = self.store.create_release(
            champion_version=champion_version,
            challenger_version=challenger_version,
            release_id=release_id,
        )
        self.telemetry.set_stage(release.id, release.stage.value)
        return release

    def predict(
        self,
        release_id: str,
        entity_id: str,
        features: FeatureVector,
        prediction_id: str | None = None,
    ) -> PredictionResponse:
        release = self.store.get_release(release_id)
        request_hash = self._request_hash(release_id, entity_id, features)
        if prediction_id is not None:
            existing = self.store.get_prediction(prediction_id)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different prediction request"
                    )
                return self._stored_response(existing, release)
        expected_features = set(self.registry.feature_names)
        received_features = set(features.root)
        if received_features != expected_features:
            missing = sorted(expected_features - received_features)
            unexpected = sorted(received_features - expected_features)
            raise PredictionContractError(
                f"feature schema mismatch; missing={missing}, unexpected={unexpected}"
            )
        values = np.asarray(
            [[features.root[name] for name in self.registry.feature_names]], dtype=float
        )
        served_role = self._served_role(release, entity_id)
        shadow_role = "champion" if served_role == "challenger" else "challenger"
        served_version = (
            release.challenger_version if served_role == "challenger" else release.champion_version
        )
        shadow_version = (
            release.champion_version if served_role == "challenger" else release.challenger_version
        )
        probability, served_latency = self._score(release.id, served_role, served_version, values)
        prediction = int(probability >= 0.5)
        pair_wanted = release.stage in {ReleaseStage.SHADOW, ReleaseStage.CANARY}

        identifier = prediction_id or f"pred-{uuid4().hex}"
        scores: dict[str, float | None] = {"champion": None, "challenger": None}
        predictions: dict[str, int | None] = {"champion": None, "challenger": None}
        latencies: dict[str, float | None] = {"champion": None, "challenger": None}
        scores[served_role] = probability
        predictions[served_role] = prediction
        latencies[served_role] = served_latency
        record = PredictionRecord(
            id=identifier,
            release_id=release.id,
            entity_id=entity_id,
            observed_at=utc_now(),
            release_stage=release.stage,
            features=dict(features.root),
            served_version=served_version,
            champion_score=scores["champion"],
            challenger_score=scores["challenger"],
            champion_prediction=predictions["champion"],
            challenger_prediction=predictions["challenger"],
            champion_latency_ms=latencies["champion"],
            challenger_latency_ms=latencies["challenger"],
            request_hash=request_hash,
            pending_role=shadow_role if pair_wanted else None,
        )
        self.store.add_prediction(record)
        self.telemetry.predictions.labels(release.id, release.stage.value, served_role).inc()
        if pair_wanted:
            self._submit_shadow(identifier, release.id, shadow_role, shadow_version, values)
        return PredictionResponse(
            prediction_id=identifier,
            prediction=prediction,
            probability=probability,
            served_version=served_version,
            release_stage=release.stage.value,
            shadow_evaluated=release.stage in {ReleaseStage.SHADOW, ReleaseStage.CANARY},
        )

    def _submit_shadow(
        self,
        prediction_id: str,
        release_id: str,
        role: str,
        version: str,
        values: np.ndarray,
    ) -> None:
        """Score the model that is not answering this request, outside the response path."""
        if self._shadow_pool is None:
            self._score_shadow(prediction_id, release_id, role, version, values)
            return
        future = self._shadow_pool.submit(
            self._score_shadow, prediction_id, release_id, role, version, values
        )
        self._shadow_futures.add(future)
        future.add_done_callback(self._shadow_futures.discard)

    def _score_shadow(
        self,
        prediction_id: str,
        release_id: str,
        role: str,
        version: str,
        values: np.ndarray,
    ) -> None:
        try:
            score, latency = self._score(release_id, role, version, values)
            self.store.complete_shadow_score(prediction_id, role, score, int(score >= 0.5), latency)
        except Exception as error:
            self.telemetry.shadow_scores.labels(release_id, role, "failed").inc()
            self.store.fail_shadow_score(prediction_id, f"{type(error).__name__}: {error}")
            LOGGER.warning(
                "shadow scoring failed for prediction %s (%s): %s", prediction_id, role, error
            )
            return
        self.telemetry.shadow_scores.labels(release_id, role, "completed").inc()

    def add_feedback(self, prediction_id: str, label: int) -> bool:
        idempotent = self.store.add_feedback(prediction_id, label)
        release_id = self.store.release_for_prediction(prediction_id)
        if not idempotent:
            self.telemetry.feedback.labels(release_id).inc()
        return idempotent

    def evaluate(self, release_id: str) -> EvidenceReport:
        release = self.store.get_release(release_id)
        observations = self.store.observations(release_id, release.stage)
        snapshot = calculate_evidence(
            observations,
            self.registry.reference_profile,
            champion_version=release.champion_version,
            min_segment_predictions=self.policy.evidence.min_segment_predictions,
        )
        report = decide(release, snapshot, self.policy)
        self.telemetry.label_coverage.labels(release.id, release.stage.value).set(
            report.label_coverage
        )
        psi = report.metrics.get("max_feature_psi")
        if psi is not None:
            self.telemetry.max_feature_psi.labels(release.id, release.stage.value).set(psi)
        gap = report.metrics.get("max_label_coverage_gap")
        if gap is not None:
            self.telemetry.label_coverage_gap.labels(release.id, release.stage.value).set(gap)
        incomplete = self.store.incomplete_prediction_counts(release.id)
        self.telemetry.incomplete_pairs.labels(release.id, "pending").set(incomplete["pending"])
        self.telemetry.incomplete_pairs.labels(release.id, "failed").set(incomplete["failed"])
        return report

    def reconcile(self, release_id: str) -> tuple[EvidenceReport, Release]:
        release = self.store.get_release(release_id)
        report = self.evaluate(release_id)
        if report.action.value == "hold" and release.last_decision == "hold":
            return report, release
        next_stage, weight = next_state(release, report.action, self.policy)
        payload = report.to_dict()
        payload["resulting_stage"] = next_stage.value
        payload["resulting_canary_weight"] = weight
        payload["resulting_revision"] = release.revision + 1
        updated = self.store.update_release(
            release.id,
            stage=next_stage,
            canary_weight=weight,
            last_decision=report.action.value,
            expected_revision=release.revision,
            audit_event_type="release.decision",
            audit_payload=payload,
        )
        for reason in report.reason_codes:
            self.telemetry.decisions.labels(release.id, report.action.value, reason).inc()
        self.telemetry.set_stage(release.id, updated.stage.value)
        return report, updated

    def _score(
        self,
        release_id: str,
        role: str,
        version: str,
        values: np.ndarray,
    ) -> tuple[float, float]:
        started = time.perf_counter()
        score = self.gateway.score(version, values)
        elapsed_seconds = time.perf_counter() - started
        self.telemetry.inference_latency.labels(release_id, role).observe(elapsed_seconds)
        if not 0.0 <= score <= 1.0:
            raise PredictionContractError(f"model {version} returned an invalid probability")
        return score, elapsed_seconds * 1000.0

    @staticmethod
    def _served_role(release: Release, entity_id: str) -> str:
        if release.stage is ReleaseStage.PROMOTED:
            return "challenger"
        if release.stage is not ReleaseStage.CANARY:
            return "champion"
        bucket = int(hashlib.sha256(entity_id.encode()).hexdigest()[:8], 16) % 10_000
        return "challenger" if bucket < release.canary_weight * 100 else "champion"

    def snapshot(self, release_id: str) -> dict[str, Any]:
        release = self.store.get_release(release_id)
        report = self.evaluate(release_id)
        return {"release": release.to_dict(), "evidence": report.to_dict()}

    @staticmethod
    def _request_hash(release_id: str, entity_id: str, features: FeatureVector) -> str:
        canonical = json.dumps(
            {
                "release_id": release_id,
                "entity_id": entity_id,
                "features": features.model_dump(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _stored_response(existing: dict[str, Any], release: Release) -> PredictionResponse:
        served_version = str(existing["served_version"])
        challenger_served = served_version == release.challenger_version
        probability = float(
            existing["challenger_score"] if challenger_served else existing["champion_score"]
        )
        prediction = int(
            existing["challenger_prediction"]
            if challenger_served
            else existing["champion_prediction"]
        )
        return PredictionResponse(
            prediction_id=str(existing["id"]),
            prediction=prediction,
            probability=probability,
            served_version=served_version,
            release_stage=str(existing["release_stage"]),
            shadow_evaluated=str(existing["release_stage"]) in {"shadow", "canary"},
        )
