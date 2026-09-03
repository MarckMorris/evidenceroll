# Changelog

All notable changes follow Keep a Changelog principles. The project uses semantic versioning after
the initial pre-1.0 period.

## [Unreleased]

### Fixed

- shadow-side model scoring now runs off the caller's response path (`EVIDENCEROLL_SHADOW_SCORING`,
  default `background`); a slow or unreachable challenger endpoint can no longer add latency to
  champion traffic ([ADR-006](docs/adr/006-shadow-scoring-runs-off-the-response-path.md));
- an absent quality metric (`accuracy_delta_ci_lower`, `brier_delta`) now blocks promotion with
  `QUALITY_EVIDENCE_UNAVAILABLE` instead of silently satisfying the gate;
- a half-scored or permanently failed prediction pair is excluded from every evidence window
  instead of being read with a missing value.

### Added

- per-segment label-coverage check (`max_label_coverage_gap`, `min_segment_predictions`) that holds
  promotion when delayed feedback is selective across served role, predicted class, or a
  reference-profile feature bin (`BIASED_LABEL_MISSINGNESS`, `LABEL_MISSINGNESS_UNVERIFIED`);
- `biased-feedback` acceptance scenario exercising the missingness gate;
- `evidenceroll_shadow_scores_total`, `evidenceroll_incomplete_pairs`, and
  `evidenceroll_label_coverage_gap` metrics;
- [ADR-005](docs/adr/005-evaluation-frequency-inflates-false-rollbacks.md) documenting that repeated
  reconciliation against a growing evidence window inflates the false-rollback rate, with the
  planned 0.2 remediation (alpha spending or mSPRT, McNemar's test for paired accuracy).

### Changed

- `predictions.champion_score` / `challenger_score` and related columns are now nullable; an
  existing `0.1.0` database is migrated automatically on open.

## [0.1.0] - 2026-09-02

### Added

- paired champion/challenger shadow and deterministic canary routing;
- delayed-label ingestion with idempotency and conflict detection;
- evidence sufficiency, freshness, PSI, disagreement, latency, accuracy, calibration and AUC metrics;
- fail-closed policy controller and four-state release lifecycle;
- local joblib, generic HTTP and KServe V2 scoring adapters;
- artifact digest verification and hash-chained decision audit;
- FastAPI, OpenAPI, dashboard, Prometheus metrics and Argo-facing verdict;
- Docker Compose observability stack and hardened Kubernetes baseline;
- deterministic scenario corpus, tests, CI, ADRs and incident runbooks.

