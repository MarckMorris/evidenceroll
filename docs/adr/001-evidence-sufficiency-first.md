# ADR-001: Treat missing evidence as a blocking state

**Status:** accepted  
**Date:** 2026-09-02

## Context

Operational canaries can complete before delayed ground truth exists. Treating no observed quality
failure as a pass converts unknown quality into permission to increase exposure.

## Decision

EvidenceRoll uses an explicit `HOLD` action. Minimum predictions, labels, coverage and freshness are
evaluated before any model-quality pass can authorize a transition. `HOLD` is represented to Argo as
`Inconclusive`, not `Successful`.

## Consequences

- Promotions wait for declared evidence.
- Feedback pipeline reliability becomes part of release reliability.
- Teams must select timeouts and escalation paths for releases that remain held.
- Proxy signals may hold or reduce exposure but cannot silently substitute for missing labels.

