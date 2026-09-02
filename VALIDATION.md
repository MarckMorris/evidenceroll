# Validation Record

**Release:** `0.1.0`  
**Validation date:** 2026-09-02  
**Primary clean environment:** CPython 3.12.13 on Linux

This record distinguishes tests that were executed locally from checks delegated to CI or a target
cluster. The synthetic corpus verifies controller behavior only; it is not a throughput, business,
or real-world model-quality benchmark.

## Executed successfully

| Check | Reproduced result |
|---|---|
| clean editable installation with development dependencies | passed |
| Ruff lint | no findings |
| Ruff format check | all files formatted |
| strict mypy, Python 3.10 language target | no issues in 16 source files |
| pytest unit, integration, contract, and failure scenarios | 63 passed |
| branch-aware coverage | 89.30%; required floor 88% |
| dependency audit in isolated project environment | no known vulnerabilities |
| PEP 517 isolated sdist and wheel build | passed |
| fresh wheel-only installation | passed |
| installed-wheel healthy scenario | `shadow -> canary -> promoted`; audit valid |
| live installed-wheel HTTP smoke test | health, readiness, create, inference, idempotent replay, feedback, evidence, Argo, audit, and metrics passed |
| shell syntax | passed for `acceptance.sh` and `verify.sh` |
| deterministic safety corpus | EvidenceRoll 4/4; HTTP-health-only baseline 1/4 |

The detailed authored-corpus output is stored in
[`evidence/benchmark-results.json`](evidence/benchmark-results.json).

## Test coverage includes

- all four controller outcomes and terminal-state protection;
- minimum volume, delayed-label coverage, feedback freshness, shift, disagreement, latency,
  non-inferiority, and calibration branches;
- stage-exclusive evidence windows and deterministic entity routing;
- prediction and feedback idempotency, conflicting labels, and stale revisions;
- atomic release-transition plus audit-event commit;
- SHA-256 model artifact tampering and audit-chain tampering;
- dynamic registry feature schemas and reference-profile lineage;
- generic HTTP and KServe V2 request/response adapters;
- API authentication, validation, error mapping, telemetry, and dashboard delivery;
- Kubernetes, Argo, Compose, alert, and Grafana asset structure.

## Environment-limited checks

Docker, Kubernetes, Kustomize, Kind, and ShellCheck executables were not available in the validation
environment. No live container or cluster result is claimed. Their assets were parsed and checked by
contract tests; GitHub Actions builds the Dockerfile independently and executes the Python matrix on
3.10, 3.11, and 3.12. A target-cluster owner must still run image scanning, admission-policy checks,
Argo CRD validation, load testing, backup restore, and rollback game days before production use.

The Argo web-metric fields were checked against the current official web-provider documentation.
CRDs evolve independently, so the deployment guide still requires validation against the exact Argo
version installed in the target cluster.

## Reproduction

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
./scripts/verify.sh
python -m evidenceroll.cli benchmark --output benchmark-results.json
```
