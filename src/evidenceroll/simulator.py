"""Executable acceptance scenarios and a declared synthetic benchmark corpus."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from evidenceroll.acceptance_fixtures import as_feature_dict, generate_churn_batch
from evidenceroll.config import Policy
from evidenceroll.registry import ModelRegistry, create_acceptance_registry
from evidenceroll.schemas import FeatureVector
from evidenceroll.service import EvidenceRollService
from evidenceroll.store import SQLiteStore

SCENARIOS = ("healthy", "regressed", "missing-feedback", "covariate-shift")


def run_scenario(
    scenario: str,
    home: Path,
    policy_path: Path,
    batch_size: int = 240,
    reset: bool = False,
) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    if reset:
        safe_reset(home)
    registry_path = home / "registry"
    create_acceptance_registry(registry_path)
    service = EvidenceRollService(
        store=SQLiteStore(home / "evidenceroll.db"),
        registry=ModelRegistry(registry_path),
        policy=Policy.from_yaml(policy_path),
    )
    challenger = "challenger-bad" if scenario == "regressed" else "challenger-good"
    release_id = f"{scenario}-{uuid4().hex[:8]}"
    release = service.create_release("champion", challenger, release_id)
    decisions: list[dict[str, Any]] = []

    shifted = scenario == "covariate-shift"
    include_feedback = scenario != "missing-feedback"
    _ingest_batch(
        service,
        release.id,
        size=batch_size,
        seed=8001,
        shifted=shifted,
        include_feedback=include_feedback,
    )
    report, release = service.reconcile(release.id)
    decisions.append(report.to_dict())

    if scenario == "healthy" and release.stage.value == "canary":
        _ingest_batch(
            service,
            release.id,
            size=batch_size,
            seed=8002,
            shifted=False,
            include_feedback=True,
        )
        report, release = service.reconcile(release.id)
        decisions.append(report.to_dict())

    return {
        "scenario": scenario,
        "synthetic_fixture": True,
        "release": release.to_dict(),
        "decisions": decisions,
        "audit_integrity": service.store.verify_audit_chain(release.id),
    }


def run_benchmark(policy_path: Path, batch_size: int = 240) -> dict[str, Any]:
    expectations = {
        "healthy": "promoted",
        "regressed": "rolled_back",
        "missing-feedback": "shadow",
        "covariate-shift": "shadow",
    }
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="evidenceroll-benchmark-") as temporary:
        root = Path(temporary)
        for scenario in SCENARIOS:
            result = run_scenario(
                scenario,
                root / scenario,
                policy_path,
                batch_size=batch_size,
            )
            actual = str(result["release"]["stage"])
            expected = expectations[scenario]
            naive_http_only = "promoted"
            cases.append(
                {
                    "scenario": scenario,
                    "expected_stage": expected,
                    "evidenceroll_stage": actual,
                    "evidenceroll_correct": actual == expected,
                    "http_only_stage": naive_http_only,
                    "http_only_correct": naive_http_only == expected,
                    "final_action": result["decisions"][-1]["action"],
                    "reason_codes": result["decisions"][-1]["reason_codes"],
                }
            )
    evidence_correct = sum(bool(case["evidenceroll_correct"]) for case in cases)
    naive_correct = sum(bool(case["http_only_correct"]) for case in cases)
    return {
        "benchmark": "synthetic-release-safety-corpus-v1",
        "disclaimer": (
            "These authored scenarios validate controller behaviour; they do not measure "
            "real-world model quality or superiority over another product."
        ),
        "case_count": len(cases),
        "evidenceroll_correct": evidence_correct,
        "http_only_correct": naive_correct,
        "cases": cases,
    }


def _ingest_batch(
    service: EvidenceRollService,
    release_id: str,
    size: int,
    seed: int,
    shifted: bool,
    include_feedback: bool,
) -> None:
    values, labels = generate_churn_batch(size, seed=seed, covariate_shift=shifted)
    pending: list[tuple[str, int]] = []
    for index, (row, label) in enumerate(zip(values, labels, strict=True)):
        response = service.predict(
            release_id=release_id,
            entity_id=f"customer-{seed}-{index}",
            features=FeatureVector.model_validate(as_feature_dict(row)),
        )
        pending.append((response.prediction_id, int(label)))
    if include_feedback:
        for prediction_id, label in pending:
            service.add_feedback(prediction_id, label)


def safe_reset(home: Path) -> None:
    resolved = home.resolve()
    if resolved in {Path("/").resolve(), Path.home().resolve()} or len(resolved.parts) < 3:
        raise ValueError(f"refusing to reset unsafe path: {resolved}")
    database = resolved / "evidenceroll.db"
    if database.exists():
        database.unlink()
    registry = resolved / "registry"
    if registry.exists():
        shutil.rmtree(registry)


def benchmark_json(policy_path: Path, batch_size: int = 240) -> str:
    return json.dumps(run_benchmark(policy_path, batch_size), indent=2, sort_keys=True) + "\n"
