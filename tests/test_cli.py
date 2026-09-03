from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evidenceroll import cli


def test_cli_initializes_and_verifies_registry(
    tmp_path: Path, policy_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "runtime"
    assert cli.main(["init", "--home", str(home), "--policy", str(policy_path)]) == 0
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["status"] == "initialized"
    assert cli.main(["verify-model", "champion", "--registry", str(home / "registry")]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert len(verified["sha256"]) == 64


def test_cli_initializes_production_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = tmp_path / "registry"
    assert (
        cli.main(
            [
                "registry-init",
                "--registry",
                str(registry),
                "--feature",
                "amount",
                "--feature",
                "risk_score",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["features"] == ["amount", "risk_score"]


def test_cli_writes_benchmark(
    tmp_path: Path, policy_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "result.json"
    assert (
        cli.main(
            [
                "benchmark",
                "--policy",
                str(policy_path),
                "--batch-size",
                "180",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    from evidenceroll.simulator import SCENARIOS

    assert json.loads(output.read_text(encoding="utf-8"))["evidenceroll_correct"] == len(SCENARIOS)
    assert json.loads(capsys.readouterr().out)["case_count"] == len(SCENARIOS)


def test_cli_profiles_reference_csv(
    tmp_path: Path, registry_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = tmp_path / "registry"
    shutil.copytree(registry_path, registry)
    source = tmp_path / "reference.csv"
    source.write_text(
        "sessions_30d,avg_order_value,days_since_last_order,support_tickets,discount_ratio\n"
        + "\n".join(f"{index},50,10,1,0.2" for index in range(3))
        + "\n",
        encoding="utf-8",
    )
    assert (
        cli.main(
            [
                "profile-reference",
                str(source),
                "--registry",
                str(registry),
                "--min-rows",
                "3",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["rows"] == 3


def test_cli_returns_distinct_error_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["verify-model", "missing", "--registry", "/does/not/exist"])
    assert code == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_cli_serve_passes_explicit_bind_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, policy_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake_run(app: object, host: str, port: int) -> None:
        seen.update({"app": app, "host": host, "port": port})

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    result = cli.main(
        [
            "serve",
            "--home",
            str(tmp_path / "runtime"),
            "--policy",
            str(policy_path),
            "--host",
            "127.0.0.1",
            "--port",
            "8099",
        ]
    )
    assert result == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8099
