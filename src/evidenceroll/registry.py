"""Model registry with artifact integrity, remote endpoints, and reference profiles."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from evidenceroll.acceptance_fixtures import FEATURE_NAMES, generate_churn_batch


class ProbabilisticClassifier(Protocol):
    def predict_proba(self, values: NDArray[np.float64]) -> NDArray[np.float64]: ...


class RegistryError(RuntimeError):
    """Registry metadata or artifact is missing or invalid."""


def _validate_feature_names(features: list[str]) -> tuple[str, ...]:
    if not features or len(features) > 256 or len(set(features)) != len(features):
        raise RegistryError("feature schema must contain 1 to 256 unique names")
    for name in features:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
            raise RegistryError(f"invalid feature name: {name!r}")
    return tuple(features)


class FirstThreeFeatures(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """Deliberately limited champion feature set for the synthetic comparison."""

    def fit(self, values: NDArray[np.float64], labels: NDArray[np.int64]) -> FirstThreeFeatures:
        del values, labels
        return self

    def transform(self, values: NDArray[np.float64]) -> NDArray[np.float64]:
        return values[:, :3]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference_profile(values: NDArray[np.float64]) -> dict[str, dict[str, list[float]]]:
    profile: dict[str, dict[str, list[float]]] = {}
    for index, name in enumerate(FEATURE_NAMES):
        column = values[:, index]
        cut_points = np.unique(np.quantile(column, np.linspace(0.1, 0.9, 9))).tolist()
        bins = np.asarray([-np.inf, *cut_points, np.inf], dtype=float)
        counts, _ = np.histogram(column, bins=bins)
        proportions = (counts / counts.sum()).astype(float).tolist()
        profile[name] = {
            "cut_points": [float(point) for point in cut_points],
            "proportions": [float(value) for value in proportions],
        }
    return profile


def _training_metrics(
    model: ProbabilisticClassifier,
    x: NDArray[np.float64],
    y: NDArray[np.int64],
) -> dict[str, float]:
    probabilities = model.predict_proba(x)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y, predictions)),
        "brier": float(brier_score_loss(y, probabilities)),
        "roc_auc": float(roc_auc_score(y, probabilities)),
    }


def create_acceptance_registry(root: str | Path, force: bool = False) -> Path:
    """Train deterministic acceptance models and write an atomic registry manifest."""
    destination = Path(root)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists() and not force:
        return manifest_path

    versions_dir = destination / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    x_train, y_train = generate_churn_batch(6000, seed=1729)
    x_validation, y_validation = generate_churn_batch(1800, seed=1730)

    champion = Pipeline(
        [
            ("limited_features", FirstThreeFeatures()),
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(C=0.3, max_iter=1000, random_state=7)),
        ]
    ).fit(x_train[:700], y_train[:700])
    challenger_good = Pipeline(
        [
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(C=1.0, max_iter=1000, random_state=7)),
        ]
    ).fit(x_train, y_train)
    challenger_bad = Pipeline(
        [
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(C=1.0, max_iter=1000, random_state=7)),
        ]
    ).fit(x_train, 1 - y_train)

    models: dict[str, ProbabilisticClassifier] = {
        "champion": cast(ProbabilisticClassifier, champion),
        "challenger-good": cast(ProbabilisticClassifier, challenger_good),
        "challenger-bad": cast(ProbabilisticClassifier, challenger_bad),
    }
    versions: dict[str, dict[str, Any]] = {}
    for version, model in models.items():
        artifact_path = versions_dir / f"{version}.joblib"
        temporary_path = artifact_path.with_suffix(".tmp")
        joblib.dump(model, temporary_path)
        os.replace(temporary_path, artifact_path)
        versions[version] = {
            "provider": "joblib",
            "artifact": str(artifact_path.relative_to(destination)),
            "sha256": sha256_file(artifact_path),
            "training_metrics": _training_metrics(model, x_validation, y_validation),
        }

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "problem_type": "binary_classification",
        "features": list(FEATURE_NAMES),
        "versions": versions,
        "reference_profile": _reference_profile(x_train),
        "fixture_notice": "Synthetic data verifies software behaviour, not real-world validity.",
    }
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary_manifest, manifest_path)
    return manifest_path


def create_registry(
    root: str | Path,
    features: list[str],
    *,
    force: bool = False,
) -> Path:
    """Create an empty production registry without synthetic models or data."""
    normalized = _validate_feature_names(features)
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists() and not force:
        raise RegistryError(f"registry manifest already exists: {manifest_path}")
    manifest = {
        "schema_version": 1,
        "problem_type": "binary_classification",
        "features": list(normalized),
        "versions": {},
        "reference_profile": {},
    }
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest_path


class ModelRegistry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            raise RegistryError(f"registry manifest not found: {manifest_path}")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            payload.get("schema_version") != 1
            or payload.get("problem_type") != "binary_classification"
            or not isinstance(payload.get("versions"), dict)
            or not isinstance(payload.get("reference_profile"), dict)
            or not isinstance(payload.get("features"), list)
        ):
            raise RegistryError("unsupported or invalid registry manifest")
        _validate_feature_names(payload["features"])
        self.manifest: dict[str, Any] = payload
        self._manifest_path = manifest_path
        self._cache: dict[str, ProbabilisticClassifier] = {}

    @property
    def reference_profile(self) -> dict[str, dict[str, list[float]]]:
        return cast(dict[str, dict[str, list[float]]], self.manifest["reference_profile"])

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(cast(list[str], self.manifest["features"]))

    def versions(self) -> tuple[str, ...]:
        versions = cast(dict[str, Any], self.manifest["versions"])
        return tuple(sorted(versions))

    @property
    def ready(self) -> bool:
        return bool(self.versions()) and set(self.reference_profile) == set(self.feature_names)

    def verify(self, version: str) -> str:
        metadata = self._metadata(version)
        if metadata.get("provider", "joblib") != "joblib":
            return "remote-endpoint"
        artifact = self.root / str(metadata["artifact"])
        if not artifact.is_file():
            raise RegistryError(f"model artifact not found for version {version}")
        actual = sha256_file(artifact)
        expected = str(metadata["sha256"])
        if actual != expected:
            raise RegistryError(
                f"integrity check failed for {version}: expected {expected}, got {actual}"
            )
        return actual

    def load(self, version: str) -> ProbabilisticClassifier:
        if version not in self._cache:
            self.verify(version)
            artifact = self.root / str(self._metadata(version)["artifact"])
            model = joblib.load(artifact)
            if not hasattr(model, "predict_proba"):
                raise RegistryError(f"model {version} does not implement predict_proba")
            self._cache[version] = cast(ProbabilisticClassifier, model)
        return self._cache[version]

    def _metadata(self, version: str) -> dict[str, Any]:
        versions = cast(dict[str, dict[str, Any]], self.manifest["versions"])
        if version not in versions:
            raise RegistryError(f"unknown model version: {version}")
        return versions[version]

    def metadata(self, version: str) -> dict[str, Any]:
        """Return a defensive copy of non-secret model connection metadata."""
        return dict(self._metadata(version))

    def register_remote(
        self,
        version: str,
        provider: str,
        endpoint: str,
        *,
        timeout_seconds: float = 2.0,
        bearer_token_env: str | None = None,
        input_name: str = "predict",
        output_name: str = "probabilities",
        probability_field: str = "probability",
        replace: bool = False,
    ) -> None:
        if provider not in {"generic_http", "kserve_v2"}:
            raise RegistryError("remote provider must be generic_http or kserve_v2")
        if not version or not endpoint.startswith(("http://", "https://")):
            raise RegistryError("version is required and endpoint must be an HTTP(S) URL")
        if timeout_seconds <= 0:
            raise RegistryError("timeout_seconds must be positive")
        versions = cast(dict[str, dict[str, Any]], self.manifest["versions"])
        if version in versions and not replace:
            raise RegistryError(f"model version already exists: {version}; use replace explicitly")
        metadata: dict[str, Any] = {
            "provider": provider,
            "endpoint": endpoint,
            "timeout_seconds": timeout_seconds,
        }
        if bearer_token_env:
            metadata["bearer_token_env"] = bearer_token_env
        if provider == "kserve_v2":
            metadata.update({"input_name": input_name, "output_name": output_name})
        else:
            metadata["probability_field"] = probability_field
        versions[version] = metadata
        self._write_manifest()
        self._cache.pop(version, None)

    def profile_reference_csv(self, source: str | Path, *, min_rows: int = 100) -> int:
        """Replace the drift reference profile from an approved numeric CSV snapshot."""
        if min_rows < 2:
            raise RegistryError("min_rows must be at least 2")
        path = Path(source)
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            fieldnames = set(reader.fieldnames or ())
            missing = set(self.feature_names) - fieldnames
            if missing:
                raise RegistryError(
                    f"reference CSV is missing required features: {', '.join(sorted(missing))}"
                )
            rows: list[list[float]] = []
            for line_number, row in enumerate(reader, start=2):
                try:
                    values = [float(row[name]) for name in self.feature_names]
                except (TypeError, ValueError) as exc:
                    raise RegistryError(
                        f"reference CSV contains a non-numeric value at line {line_number}"
                    ) from exc
                if not np.isfinite(values).all():
                    raise RegistryError(
                        f"reference CSV contains a non-finite value at line {line_number}"
                    )
                rows.append(values)
        if len(rows) < min_rows:
            raise RegistryError(
                f"reference CSV contains {len(rows)} rows; at least {min_rows} are required"
            )
        matrix = np.asarray(rows, dtype=float)
        self.manifest["reference_profile"] = _reference_profile(matrix)
        self.manifest["reference_profile_metadata"] = {
            "row_count": len(rows),
            "source_sha256": sha256_file(path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_manifest()
        return len(rows)

    def _write_manifest(self) -> None:
        temporary = self._manifest_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self._manifest_path)
