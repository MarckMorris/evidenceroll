# Roadmap

The roadmap is deliberately separated from the verified `0.1.0` contract.

## 0.2 — pluggable evidence

- sequential-testing controller: alpha-spending boundary or mSPRT in place of the fixed-alpha
  interval, so repeated reconciliation no longer inflates the false-rollback rate
  ([ADR-005](docs/adr/005-evaluation-frequency-inflates-false-rollbacks.md));
- McNemar's test as the primary paired-accuracy statistic, with the current Wald interval kept as a
  secondary descriptive metric;
- signal-provider interface for Evidently/NannyML-style reports;
- protected-attribute review workflow on top of the label-missingness segments shipped in this
  release;
- event-time windows and explicit late-arrival watermarks;
- signed policy bundles and independent chain-head export.

## 0.3 — multi-writer persistence

- PostgreSQL store and migrations;
- transactional release transition plus audit outbox;
- per-release leases and horizontally scaled read API;
- concurrency, failover and restore benchmarks against a live database.

## 0.4 — orchestration

- Kubernetes custom resource and controller;
- KServe and Argo version-tested adapters;
- webhook delivery with signatures, retries and dead-letter handling;
- MLflow alias update behind a two-phase promotion contract.

## 1.0 criteria

- backward-compatible event and policy schemas;
- multi-class and regression evidence contracts;
- measured load, recovery and long-running soak tests;
- external security review;
- production adopter feedback and documented upgrade path.

No roadmap item is claimed as implemented.

