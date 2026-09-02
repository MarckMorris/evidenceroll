"""Prometheus metrics kept in an application-local registry for test isolation."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class Telemetry:
    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.predictions = Counter(
            "evidenceroll_predictions_total",
            "Predictions accepted by the release proxy.",
            ("release_id", "stage", "served_role"),
            registry=self.registry,
        )
        self.feedback = Counter(
            "evidenceroll_feedback_total",
            "Ground-truth labels joined to predictions.",
            ("release_id",),
            registry=self.registry,
        )
        self.decisions = Counter(
            "evidenceroll_decisions_total",
            "Release decisions emitted by action and reason.",
            ("release_id", "action", "reason"),
            registry=self.registry,
        )
        self.inference_latency = Histogram(
            "evidenceroll_model_inference_seconds",
            "Local model-adapter inference latency.",
            ("release_id", "role"),
            buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
            registry=self.registry,
        )
        self.release_stage = Gauge(
            "evidenceroll_release_stage",
            "One-hot release stage.",
            ("release_id", "stage"),
            registry=self.registry,
        )
        self.label_coverage = Gauge(
            "evidenceroll_label_coverage_ratio",
            "Labeled predictions divided by predictions in the current stage.",
            ("release_id", "stage"),
            registry=self.registry,
        )
        self.max_feature_psi = Gauge(
            "evidenceroll_max_feature_psi",
            "Maximum feature PSI in the current evidence window.",
            ("release_id", "stage"),
            registry=self.registry,
        )

    def set_stage(self, release_id: str, active_stage: str) -> None:
        for stage in ("shadow", "canary", "promoted", "rolled_back"):
            self.release_stage.labels(release_id, stage).set(1 if stage == active_stage else 0)

    def render(self) -> bytes:
        return generate_latest(self.registry)
