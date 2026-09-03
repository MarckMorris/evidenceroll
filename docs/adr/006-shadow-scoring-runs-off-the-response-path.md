# ADR-006: Shadow-side scoring must not block the caller's response

**Status:** accepted
**Date:** 2026-09-03

## Context

`0.1.0` scored the champion and the challenger sequentially, in-process, before returning a
response. With the bundled `joblib` fixtures the challenger call costs microseconds and the defect
is invisible. It stops being invisible the moment a release is wired to `generic_http` or
`kserve_v2`: the caller's latency becomes champion latency plus the full round trip to a model whose
result the caller never sees. That directly contradicts the point of a shadow deployment, which is
supposed to let a challenger be evaluated with zero latency or availability impact on production
traffic. A slow, degraded, or briefly unreachable challenger endpoint would have silently become a
production incident for the champion path.

## Decision

Score the side that answers the caller inline, and score the shadow side out of the response path.

- `EvidenceRollService` gains a `shadow_scoring` mode: `"inline"` (the previous behavior, kept for
  tests and single-threaded embedding) and `"background"` (default for the FastAPI app), backed by a
  `ThreadPoolExecutor`. `predict()` always scores the serving side itself; the non-serving side is
  submitted to the pool (or scored inline as a plain function call in `"inline"` mode) and does not
  block the return value.
- A prediction row can now be stored with one side `NULL`. `predictions.pending_role` names the
  side still in flight; `shadow_error` records a permanently failed attempt. `SQLiteStore` migrates
  a pre-0.2 predictions table (all columns `NOT NULL`) to the nullable schema on open, preserving
  existing rows — no manual migration step.
- `SQLiteStore.observations()` — the only read path the evidence engine sees — now filters to
  `pending_role IS NULL AND shadow_error IS NULL AND champion_score IS NOT NULL AND
  challenger_score IS NOT NULL`. A half-scored or abandoned pair is excluded from every evidence
  window; it is neither promoting nor blocking evidence, it simply is not evidence yet. This
  preserves the fail-closed invariant instead of extending it: a pair that never completes just
  never counts, the same way a request that was never sent never counted.
- A failed shadow score does not retry silently and does not guess a value. `fail_shadow_score()`
  marks the row `shadow_error` and it is permanently excluded; the failure is visible through
  `evidenceroll_shadow_scores_total{outcome="failed"}` and `evidenceroll_incomplete_pairs{state=
  "failed"}` so a sustained failure rate on one adapter is an operational signal, not a silent
  reduction in effective sample size.
- `EvidenceRollService.flush_shadow()` waits for in-flight background work (used by tests and by
  graceful shutdown); `close()` shuts the pool down. The FastAPI lifespan now flushes and closes the
  pool on shutdown so in-flight shadow scores are not silently dropped mid-request.

## Consequences

- `EVIDENCEROLL_SHADOW_SCORING` (`background` default) and `EVIDENCEROLL_SHADOW_WORKERS` (default
  `2`) are new environment variables, documented in `.env.example` and `docs/operations.md`.
- Champion latency in the response path is now independent of challenger adapter latency and
  availability. `evidenceroll_model_inference_seconds` still records both sides' latency, labeled by
  role, so the challenger's real latency remains observable — it just no longer gates the caller.
- A release under sustained challenger-endpoint failure accumulates `shadow_error` rows and stalls in
  its current stage (fewer complete pairs, not zero — the champion side is still recorded). This is
  visible via `incomplete_pairs{state="failed"}` and is the intended behavior: an unreachable
  challenger cannot forge evidence for itself by omission, and it cannot degrade champion traffic
  either.
- Local `joblib` scoring still runs the same code path; because it is CPU-bound and the GIL applies,
  background mode does not parallelize it further, but it does move the model call off the
  request-handling coroutine so a slow deserialization or CPU spike in the shadow model cannot delay
  the champion's own response.
- The predictions schema change (nullable score columns, `pending_role`, `shadow_error`) is
  backward-compatible: `SQLiteStore._migrate_pending_shadow_columns()` runs once against an existing
  database and leaves fully-scored historical rows untouched and readable.
