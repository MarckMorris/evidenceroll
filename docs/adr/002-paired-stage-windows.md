# ADR-002: Store paired predictions in stage-specific windows

**Status:** accepted  
**Date:** 2026-09-02

## Context

Comparing a champion on yesterday's traffic with a challenger on today's traffic confounds model
change with population change. Combining shadow and canary observations also hides which evidence
was collected under customer exposure.

## Decision

Both models score the same feature vector. One event stores both scores, decisions and timings plus
the release stage at inference time. Reconciliation reads only the current stage's window.

## Consequences

- Accuracy deltas use matched cases.
- Shadow evidence cannot automatically satisfy the canary gate.
- Challenger scoring adds latency and compute cost even when its answer is not served.
- Remote endpoints must tolerate shadow load or use a sampling layer upstream.

