# ADR-005: Repeated evaluation inflates the false-rollback rate

**Status:** accepted, unresolved for `0.1.0`
**Date:** 2026-09-03

## Context

`decide()` computes a fresh 95% confidence interval on the paired accuracy delta
(`paired_accuracy_interval`) every time `reconcile()` runs. Nothing prevents `reconcile()` from
running many times against the same accumulating evidence window: a human can call it manually, or
`EVIDENCEROLL_RECONCILE_INTERVAL_SECONDS` can call it every five seconds for as long as a release
stays in `shadow` or `canary`.

A single 95% interval controls the false-rollback rate at 5% for one look at one fixed sample. It
does not control it across repeated looks at a growing sample. This is the classical sequential-
testing multiplicity problem: each reconciliation is a new hypothesis test against the same
non-inferiority margin, and the tests are correlated because each window is a superset of the
previous one.

A back-of-envelope bound: with `k` independent-enough looks, the chance that at least one crosses
the 5%-per-look threshold approaches `1 - (0.95)^k` under the null (no real regression). At `k = 12`
(one hour of five-minute reconciliation) that is already `~46%`. In practice the looks are strongly
correlated, not independent, so the true inflation is smaller than this bound — but the bound is the
right order of magnitude for why this is a real defect, not a rounding error.

The consequence is asymmetric with the project's own thesis. EvidenceRoll's stated invariant is that
absence of evidence must never produce a false promotion. This defect produces the opposite failure:
a healthy challenger has an elevated chance of being rolled back purely because the controller looked
at the data too many times, not because the model regressed. A team that reacts to that by widening
`non_inferiority_margin` to stop the false alarms quietly reintroduces the risk the margin exists to
bound.

A secondary, smaller issue in the same statistic: `paired_accuracy_interval` computes a Wald interval
on per-observation deltas in `{-1, 0, 1}`. For paired binary outcomes the standard approach is
McNemar's test (or its continuity-corrected / exact variant) on the discordant pairs — cases where
champion and challenger disagree and one is correct. The Wald approximation is reasonable at the
volumes `policy.yaml` requires (`min_labels: 90`+) but degrades as the discordant count shrinks,
which is exactly the low-disagreement regime a conservative rollout produces.

## Decision

Ship `0.1.0` with the defect documented rather than silently declared safe. `README.md` and
`docs/project-walkthrough.md` already state "not a regulated sequential-testing implementation";
this ADR is the record of *why*, with the math, so the boundary is falsifiable rather than a
disclaimer.

No code change ships against this ADR in `0.1.0`. The two changes that would resolve it are both
breaking to the evidence contract (the digest payload and the reason-code vocabulary), so they
belong to a minor version with their own migration note, not folded into the missingness and
async-shadow work landing alongside this ADR.

## Planned resolution (0.2)

1. Replace the fixed-alpha Wald interval with a sequential testing procedure — either an alpha-
   spending function (O'Brien-Fleming or Pocock boundary, since the reconciliation cadence is
   already fixed by policy) or a mixture-SPRT (mSPRT), which does not require pre-declaring the
   number of looks.
2. Replace the Wald delta with McNemar's test (or its exact variant below a discordant-pair floor)
   as the primary paired-accuracy statistic; keep the current interval as a secondary descriptive
   metric in the evidence payload.
3. Add a policy field for the total error budget across the release lifetime, not per look, and
   make the evidence digest record cumulative looks-to-date so an audit can reconstruct the actual
   achieved false-rollback rate.
4. Add a regression test that runs `reconcile()` in a tight loop against a truly non-inferior
   synthetic challenger and asserts the empirical rollback rate stays within a stated bound — this
   is the test that would have caught the present defect.

## Consequences

- Until 0.2, operators should treat `EVIDENCEROLL_RECONCILE_INTERVAL_SECONDS` conservatively: fewer,
  larger evidence windows reduce (without eliminating) the multiplicity problem. This is now stated
  in `docs/operations.md`.
- The declared acceptance benchmark (`evidenceroll.cli benchmark`) is unaffected: each scenario
  reconciles a fixed number of times by construction, so it does not exercise the defect.
- `CHANGELOG.md` and `ROADMAP.md` list the 0.2 items above so they are tracked, not just described.
