from __future__ import annotations

from pathlib import Path

import pytest

from evidenceroll.config import Policy
from evidenceroll.registry import ModelRegistry, create_acceptance_registry
from evidenceroll.service import EvidenceRollService
from evidenceroll.store import SQLiteStore


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def policy_path(project_root: Path) -> Path:
    return project_root / "config" / "policy.yaml"


@pytest.fixture(scope="session")
def registry_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("registry")
    create_acceptance_registry(root)
    return root


@pytest.fixture()
def service(tmp_path: Path, registry_path: Path, policy_path: Path) -> EvidenceRollService:
    return EvidenceRollService(
        SQLiteStore(tmp_path / "events.db"),
        ModelRegistry(registry_path),
        Policy.from_yaml(policy_path),
    )
