from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.mark.contract
def test_kustomize_references_existing_valid_yaml(project_root: Path) -> None:
    base = project_root / "deploy" / "kubernetes" / "base"
    kustomization = yaml.safe_load((base / "kustomization.yaml").read_text(encoding="utf-8"))
    for resource in kustomization["resources"]:
        target = base / resource
        assert target.is_file(), resource
        document = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert document["apiVersion"]
        assert document["kind"]
        assert document["metadata"]["name"]


@pytest.mark.contract
def test_kubernetes_baseline_enforces_single_writer_and_container_hardening(
    project_root: Path,
) -> None:
    deployment = yaml.safe_load(
        (project_root / "deploy/kubernetes/base/deployment.yaml").read_text(encoding="utf-8")
    )
    spec = deployment["spec"]
    container = spec["template"]["spec"]["containers"][0]
    security = container["securityContext"]
    assert spec["replicas"] == 1
    assert spec["strategy"]["type"] == "Recreate"
    assert security["readOnlyRootFilesystem"] is True
    assert security["allowPrivilegeEscalation"] is False
    assert security["capabilities"]["drop"] == ["ALL"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"


@pytest.mark.contract
def test_container_and_observability_assets_are_structurally_valid(project_root: Path) -> None:
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    compose = yaml.safe_load((project_root / "docker-compose.yml").read_text(encoding="utf-8"))
    assert {"control-plane", "prometheus", "grafana"} <= set(compose["services"])
    alerts = yaml.safe_load((project_root / "observability/alerts.yml").read_text(encoding="utf-8"))
    assert len(alerts["groups"][0]["rules"]) >= 3
    dashboard = json.loads(
        (project_root / "observability/grafana/dashboards/evidenceroll.json").read_text(
            encoding="utf-8"
        )
    )
    assert dashboard["uid"] == "evidenceroll"
    assert len(dashboard["panels"]) >= 5


@pytest.mark.contract
def test_argo_template_is_valid_yaml(project_root: Path) -> None:
    document = yaml.safe_load(
        (project_root / "deploy/kubernetes/argo-analysis-template.yaml").read_text(encoding="utf-8")
    )
    assert document["kind"] == "AnalysisTemplate"
    metric = document["spec"]["metrics"][0]
    assert metric["successCondition"]
    assert metric["failureCondition"]
    assert metric["failureLimit"] == 1
    assert metric["consecutiveSuccessLimit"] == 1
    assert metric["provider"]["web"]["url"].endswith("/analysis")
