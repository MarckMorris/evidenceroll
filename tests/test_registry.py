from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from evidenceroll.registry import ModelRegistry, RegistryError, create_registry


def test_acceptance_registry_has_three_verified_versions(registry_path: Path) -> None:
    registry = ModelRegistry(registry_path)
    assert registry.versions() == ("challenger-bad", "challenger-good", "champion")
    digest = registry.verify("champion")
    assert len(digest) == 64
    probabilities = registry.load("champion").predict_proba(
        np.asarray([[10.0, 50.0, 20.0, 1.0, 0.2]])
    )
    assert probabilities.shape == (1, 2)
    assert registry.ready is True


def test_empty_production_registry_requires_profile_and_model(tmp_path: Path) -> None:
    path = tmp_path / "production"
    create_registry(path, ["amount", "risk_score"])
    registry = ModelRegistry(path)
    assert registry.feature_names == ("amount", "risk_score")
    assert registry.ready is False
    with pytest.raises(RegistryError, match="already exists"):
        create_registry(path, ["amount"])


def test_integrity_check_detects_artifact_tampering(tmp_path: Path, registry_path: Path) -> None:
    clone = tmp_path / "registry"
    shutil.copytree(registry_path, clone)
    manifest = json.loads((clone / "manifest.json").read_text(encoding="utf-8"))
    artifact = clone / manifest["versions"]["champion"]["artifact"]
    artifact.write_bytes(artifact.read_bytes() + b"tamper")
    with pytest.raises(RegistryError, match="integrity check failed"):
        ModelRegistry(clone).verify("champion")


def test_unknown_version_fails_closed(registry_path: Path) -> None:
    with pytest.raises(RegistryError, match="unknown model version"):
        ModelRegistry(registry_path).verify("does-not-exist")


def test_remote_endpoint_registration_contains_no_secret(
    tmp_path: Path, registry_path: Path
) -> None:
    clone = tmp_path / "registry"
    shutil.copytree(registry_path, clone)
    registry = ModelRegistry(clone)
    registry.register_remote(
        "remote-canary",
        "kserve_v2",
        "https://models.internal/v2/models/canary/infer",
        bearer_token_env="MODEL_TOKEN",
    )
    metadata = ModelRegistry(clone).metadata("remote-canary")
    assert metadata["provider"] == "kserve_v2"
    assert metadata["bearer_token_env"] == "MODEL_TOKEN"
    assert "token" not in metadata


def test_remote_registration_requires_explicit_replace(tmp_path: Path, registry_path: Path) -> None:
    clone = tmp_path / "registry"
    shutil.copytree(registry_path, clone)
    registry = ModelRegistry(clone)
    with pytest.raises(RegistryError, match="already exists"):
        registry.register_remote("champion", "generic_http", "https://model.internal/predict")
    registry.register_remote(
        "champion", "generic_http", "https://model.internal/predict", replace=True
    )
    assert ModelRegistry(clone).metadata("champion")["provider"] == "generic_http"


def test_reference_profile_is_built_from_validated_csv(tmp_path: Path, registry_path: Path) -> None:
    clone = tmp_path / "registry"
    shutil.copytree(registry_path, clone)
    source = tmp_path / "reference.csv"
    source.write_text(
        "sessions_30d,avg_order_value,days_since_last_order,support_tickets,discount_ratio\n"
        + "\n".join(f"{index},{50 + index},10,1,0.2" for index in range(100))
        + "\n",
        encoding="utf-8",
    )
    registry = ModelRegistry(clone)
    assert registry.profile_reference_csv(source) == 100
    refreshed = ModelRegistry(clone)
    assert refreshed.manifest["reference_profile_metadata"]["row_count"] == 100
    assert len(refreshed.manifest["reference_profile_metadata"]["source_sha256"]) == 64


def test_reference_profile_rejects_invalid_csv(tmp_path: Path, registry_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text("sessions_30d\n1\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="missing required features"):
        ModelRegistry(registry_path).profile_reference_csv(source)


@pytest.mark.parametrize(
    ("provider", "endpoint"),
    [("unknown", "https://models.internal/infer"), ("generic_http", "file:///model")],
)
def test_remote_registration_rejects_unsafe_metadata(
    registry_path: Path, provider: str, endpoint: str
) -> None:
    registry = ModelRegistry(registry_path)
    with pytest.raises(RegistryError):
        registry.register_remote("candidate", provider, endpoint)
