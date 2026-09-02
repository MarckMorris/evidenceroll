"""Pluggable scoring adapters for local artifacts and remote inference services."""

from __future__ import annotations

import os
from typing import Any, Protocol

import httpx
import numpy as np

from evidenceroll.registry import ModelRegistry, RegistryError


class ScoringAdapter(Protocol):
    def score(self, values: np.ndarray) -> float: ...


class LocalJoblibAdapter:
    def __init__(self, registry: ModelRegistry, version: str) -> None:
        self.model = registry.load(version)

    def score(self, values: np.ndarray) -> float:
        return float(self.model.predict_proba(values)[0, 1])


class GenericHTTPAdapter:
    """Adapter for a small, explicit JSON contract documented in integrations.md."""

    def __init__(self, metadata: dict[str, Any], feature_names: tuple[str, ...]) -> None:
        self.endpoint = _required_string(metadata, "endpoint")
        self.probability_field = str(metadata.get("probability_field", "probability"))
        self.feature_names = feature_names
        self.timeout = float(metadata.get("timeout_seconds", 2.0))
        self.headers = _auth_headers(metadata)

    def score(self, values: np.ndarray) -> float:
        payload = {
            "instances": [
                dict(zip(self.feature_names, [float(value) for value in values[0]], strict=True))
            ]
        }
        response = httpx.post(
            self.endpoint,
            json=payload,
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        probability = data.get(self.probability_field)
        if isinstance(probability, list):
            probability = probability[0]
        return _probability(probability)


class KServeV2Adapter:
    """KServe V2 inference-protocol adapter for one FP64 feature tensor."""

    def __init__(self, metadata: dict[str, Any], feature_names: tuple[str, ...]) -> None:
        self.endpoint = _required_string(metadata, "endpoint")
        self.input_name = str(metadata.get("input_name", "predict"))
        self.output_name = str(metadata.get("output_name", "probabilities"))
        self.feature_names = feature_names
        self.timeout = float(metadata.get("timeout_seconds", 2.0))
        self.headers = _auth_headers(metadata)

    def score(self, values: np.ndarray) -> float:
        payload = {
            "inputs": [
                {
                    "name": self.input_name,
                    "shape": [1, len(self.feature_names)],
                    "datatype": "FP64",
                    "data": [float(value) for value in values[0]],
                }
            ]
        }
        response = httpx.post(
            self.endpoint,
            json=payload,
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        outputs = body.get("outputs", [])
        selected = next(
            (output for output in outputs if output.get("name") == self.output_name), None
        )
        if selected is None:
            raise RegistryError(f"KServe response omitted output {self.output_name}")
        data = selected.get("data")
        if not isinstance(data, list) or not data:
            raise RegistryError("KServe output data must be a non-empty list")
        first = data[0]
        if isinstance(first, list):
            first = first[-1]
        return _probability(first)


class ModelGateway:
    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry
        self._adapters: dict[str, ScoringAdapter] = {}

    def score(self, version: str, values: np.ndarray) -> float:
        if version not in self._adapters:
            metadata = self.registry.metadata(version)
            provider = str(metadata.get("provider", "joblib"))
            if provider == "joblib":
                adapter: ScoringAdapter = LocalJoblibAdapter(self.registry, version)
            elif provider == "generic_http":
                adapter = GenericHTTPAdapter(metadata, self.registry.feature_names)
            elif provider == "kserve_v2":
                adapter = KServeV2Adapter(metadata, self.registry.feature_names)
            else:
                raise RegistryError(f"unsupported model provider for {version}: {provider}")
            self._adapters[version] = adapter
        return self._adapters[version].score(values)


def _required_string(metadata: dict[str, Any], name: str) -> str:
    value = metadata.get(name)
    if not isinstance(value, str) or not value:
        raise RegistryError(f"remote model metadata requires {name}")
    return value


def _auth_headers(metadata: dict[str, Any]) -> dict[str, str]:
    variable = metadata.get("bearer_token_env")
    if variable is None:
        return {}
    if not isinstance(variable, str) or not variable:
        raise RegistryError("bearer_token_env must be a non-empty environment-variable name")
    token = os.getenv(variable)
    if token is None:
        raise RegistryError(f"required model-endpoint credential is not set: {variable}")
    return {"Authorization": f"Bearer {token}"}


def _probability(value: Any) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise RegistryError("model endpoint returned a non-numeric probability")
    probability = float(value)
    if not 0.0 <= probability <= 1.0:
        raise RegistryError("model endpoint probability must be between 0 and 1")
    return probability
