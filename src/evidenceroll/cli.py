"""Command-line interface for operations, verification, and acceptance scenarios."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import uvicorn

from evidenceroll.app import create_app
from evidenceroll.config import Policy
from evidenceroll.registry import ModelRegistry, create_acceptance_registry, create_registry
from evidenceroll.simulator import SCENARIOS, run_benchmark, run_scenario
from evidenceroll.store import SQLiteStore


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="evidenceroll",
        description="Evidence-aware progressive delivery for ML models with delayed labels.",
    )
    root.add_argument("--version", action="version", version="EvidenceRoll 0.1.0")
    subcommands = root.add_subparsers(dest="command", required=True)

    initialize = subcommands.add_parser("init", help="create local fixtures and persistence")
    _common_paths(initialize)
    initialize.add_argument("--force-models", action="store_true")

    registry_init = subcommands.add_parser(
        "registry-init", help="create an empty production registry for named features"
    )
    registry_init.add_argument("--registry", type=Path, default=Path(".evidenceroll/registry"))
    registry_init.add_argument("--feature", action="append", required=True)
    registry_init.add_argument("--force", action="store_true")

    serve = subcommands.add_parser("serve", help="run the control-plane API")
    _common_paths(serve)
    serve.add_argument("--host", default=os.getenv("EVIDENCEROLL_HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.getenv("EVIDENCEROLL_PORT", "8080")))

    simulate = subcommands.add_parser("simulate", help="run an acceptance scenario")
    _common_paths(simulate)
    simulate.add_argument("--scenario", choices=SCENARIOS, default="healthy")
    simulate.add_argument("--batch-size", type=int, default=240)
    simulate.add_argument("--reset", action="store_true")

    benchmark = subcommands.add_parser("benchmark", help="run the declared synthetic corpus")
    benchmark.add_argument("--policy", type=Path, default=Path("config/policy.yaml"))
    benchmark.add_argument("--batch-size", type=int, default=240)
    benchmark.add_argument("--output", type=Path)

    verify = subcommands.add_parser("verify-model", help="verify a registered artifact digest")
    verify.add_argument("version")
    verify.add_argument("--registry", type=Path, default=Path(".evidenceroll/registry"))

    register = subcommands.add_parser(
        "register-endpoint", help="register a generic HTTP or KServe V2 model endpoint"
    )
    register.add_argument("version")
    register.add_argument("--registry", type=Path, default=Path(".evidenceroll/registry"))
    register.add_argument("--provider", choices=("generic_http", "kserve_v2"), required=True)
    register.add_argument("--endpoint", required=True)
    register.add_argument("--timeout", type=float, default=2.0)
    register.add_argument("--bearer-token-env")
    register.add_argument("--input-name", default="predict")
    register.add_argument("--output-name", default="probabilities")
    register.add_argument("--probability-field", default="probability")
    register.add_argument("--replace", action="store_true")

    profile = subcommands.add_parser(
        "profile-reference", help="build the production-shift reference profile from CSV"
    )
    profile.add_argument("source", type=Path)
    profile.add_argument("--registry", type=Path, default=Path(".evidenceroll/registry"))
    profile.add_argument("--min-rows", type=int, default=100)
    return root


def _common_paths(target: argparse.ArgumentParser) -> None:
    target.add_argument(
        "--home",
        type=Path,
        default=Path(os.getenv("EVIDENCEROLL_HOME", ".evidenceroll")),
    )
    target.add_argument(
        "--policy",
        type=Path,
        default=Path(os.getenv("EVIDENCEROLL_POLICY", "config/policy.yaml")),
    )


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        result = _dispatch(arguments)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    if result is not None:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _dispatch(arguments: argparse.Namespace) -> dict[str, Any] | None:
    if arguments.command == "init":
        home = arguments.home.resolve()
        manifest = create_acceptance_registry(home / "registry", force=arguments.force_models)
        SQLiteStore(home / "evidenceroll.db")
        policy = Policy.from_yaml(arguments.policy)
        return {
            "home": str(home),
            "registry_manifest": str(manifest),
            "policy_id": policy.policy_id,
            "status": "initialized",
        }
    if arguments.command == "registry-init":
        manifest = create_registry(
            arguments.registry.resolve(), arguments.feature, force=arguments.force
        )
        return {"registry_manifest": str(manifest), "features": arguments.feature}
    if arguments.command == "serve":
        os.environ["EVIDENCEROLL_HOME"] = str(arguments.home.resolve())
        os.environ["EVIDENCEROLL_POLICY"] = str(arguments.policy.resolve())
        uvicorn.run(create_app(), host=arguments.host, port=arguments.port)
        return None
    if arguments.command == "simulate":
        return run_scenario(
            scenario=arguments.scenario,
            home=arguments.home.resolve(),
            policy_path=arguments.policy.resolve(),
            batch_size=arguments.batch_size,
            reset=arguments.reset,
        )
    if arguments.command == "benchmark":
        result = run_benchmark(arguments.policy.resolve(), arguments.batch_size)
        if arguments.output:
            arguments.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        return result
    if arguments.command == "verify-model":
        registry = ModelRegistry(arguments.registry)
        return {"version": arguments.version, "sha256": registry.verify(arguments.version)}
    if arguments.command == "register-endpoint":
        registry = ModelRegistry(arguments.registry)
        registry.register_remote(
            arguments.version,
            arguments.provider,
            arguments.endpoint,
            timeout_seconds=arguments.timeout,
            bearer_token_env=arguments.bearer_token_env,
            input_name=arguments.input_name,
            output_name=arguments.output_name,
            probability_field=arguments.probability_field,
            replace=arguments.replace,
        )
        return {"version": arguments.version, "metadata": registry.metadata(arguments.version)}
    if arguments.command == "profile-reference":
        registry = ModelRegistry(arguments.registry)
        rows = registry.profile_reference_csv(arguments.source, min_rows=arguments.min_rows)
        metadata = registry.manifest["reference_profile_metadata"]
        return {"rows": rows, "reference_profile_metadata": metadata}
    raise ValueError(f"unknown command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
