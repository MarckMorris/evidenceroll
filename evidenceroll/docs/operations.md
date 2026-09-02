# Operations Guide

## Supported operating envelope

EvidenceRoll `0.1.0` is a single-writer release control plane. Run exactly one control-plane replica
per SQLite database. Prediction model endpoints scale independently and may be local artifacts,
generic HTTP services, or KServe V2 services.

The included Kubernetes baseline enforces this contract with one replica, `Recreate`, and a
`ReadWriteOnce` volume. Do not change the replica count without first implementing the PostgreSQL,
lease, and multi-writer acceptance criteria in [ADR-003](adr/003-single-writer-store.md).

## Recommended service objectives

These are starting objectives for an installation, not benchmark claims. Owners must replace them
with values derived from traffic, label delay, business loss, and model endpoint budgets.

| Objective | Starting target | Measurement | Failure response |
|---|---:|---|---|
| control-plane availability | 99.9% monthly | successful `/readyz` probes | restore instance or volume |
| prediction proxy success | 99.5% over 10 minutes | non-5xx prediction requests | inspect both model endpoints |
| prediction p95 | application budget minus network reserve | end-to-end client latency | hold new releases; tune endpoints |
| feedback join success | 99.9% over 30 minutes | accepted or idempotent feedback writes | stop promotion; inspect producer |
| evidence freshness | policy-specific | `evidence_age_seconds` from latest feedback | `HOLD`; repair feedback pipeline |
| audit integrity | 100% | `/audit-integrity` | freeze mutations and follow runbook |

Evidence availability is intentionally separate from API availability. A healthy API with missing
labels must stay ready to collect evidence while returning `HOLD` for release progression.

## Capacity planning

Each prediction performs two model calls, stores one paired event, and updates bounded-cardinality
metrics. Labels add one indexed row. Estimate storage from measured serialized row size rather than
from feature count alone:

```text
daily bytes = predictions_per_day × measured_prediction_row_bytes
            + labels_per_day × measured_feedback_row_bytes
            + audit_events_per_day × measured_audit_row_bytes
```

Before production cutover:

1. replay the expected feature width and request rate for at least one peak-hour window;
2. measure end-to-end p50, p95, and p99 rather than model-only latency;
3. inject timeout, slow challenger, database-full, and delayed-feedback failures;
4. verify disk growth, WAL checkpoint behavior, and backup duration;
5. set retention only after confirming audit and investigation requirements;
6. document the tested ceiling in the deployment repository.

Synthetic acceptance scenarios are not load tests and must never be cited as a throughput claim.

## Backup and recovery

The database, registry manifest, policy file, audit HMAC secret reference, and independent audit-chain
head are one recovery set. Back up the SQLite database with a storage snapshot or SQLite online backup
while the application is quiesced or using a platform method that preserves WAL consistency. Copying
only the main database file while writes continue is not a valid backup.

Recommended starting recovery objectives are RPO 5 minutes and RTO 30 minutes. Validate them through
a restore exercise; configuration alone does not establish either objective.

Recovery drill:

1. stop the writer or isolate the target deployment;
2. restore the database and registry to a new volume;
3. restore policy and secret references from versioned configuration;
4. start one replica with automatic reconciliation disabled;
5. require `/readyz` to pass and verify every active release audit chain;
6. compare the exported chain head and policy digest with the independent record;
7. perform a shadow prediction and idempotent feedback replay;
8. enable reconciliation only after the owner signs off.

## Deployment checklist

- create a production registry with `registry-init`; do not use fixture artifacts;
- build a reference profile from approved data and retain its source digest;
- register immutable champion and challenger version names;
- inject endpoint tokens and audit HMAC through the platform secret provider;
- set `EVIDENCEROLL_BOOTSTRAP_FIXTURES=false`;
- set a non-empty `EVIDENCEROLL_API_KEY` or stronger ingress identity control;
- terminate TLS and configure request-size and rate limits at ingress;
- calibrate the policy by replaying representative labeled traffic;
- route Prometheus alerts to an owned escalation path;
- export audit-chain heads to an independent system;
- run a backup restore and one rollback game day;
- connect Argo only after manual shadow reconciliation behaves as expected.

## Change management

Threshold edits require a new `policy_id`. Model versions must be immutable; endpoint replacement
requires the explicit `--replace` flag and a change record. Promotion-semantics, identity, storage,
or audit changes require an ADR and failure-path tests.

Use the provided runbooks for [model regression](runbooks/model-regression.md),
[feedback SLA failure](runbooks/feedback-sla.md), and
[audit-integrity failure](runbooks/audit-integrity.md).
