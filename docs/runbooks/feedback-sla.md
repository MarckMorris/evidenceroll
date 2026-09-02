# Runbook: delayed-feedback SLA breach

## Trigger

- `INSUFFICIENT_LABELS` or `INSUFFICIENT_LABEL_COVERAGE` persists beyond the domain's expected label
  delay;
- `EvidenceRollLabelCoverageLow` alert fires.

## Checks

1. Confirm prediction volume for the active release stage.
2. Compare label count, coverage, and latest feedback timestamp with the source system.
3. Search for orphan labels, duplicated IDs and source-side retry failures.
4. Check whether labels are missing uniformly. Missingness correlated with class, geography, device,
   or channel can bias the measured release delta.
5. Confirm time-zone and event-time conversions upstream.

## Safe response

Keep the release in `HOLD`. Do not reduce `min_labels` or `min_label_coverage` during an incident
unless the model owner, product owner, and risk owner document the changed uncertainty in a new
policy ID.

Backfill labels with the original `prediction_id`. Identical replay is idempotent; conflicting labels
return `409` and require source correction.

## Exit criteria

- arrival backlog is drained;
- coverage exceeds the policy threshold for the active stage;
- missingness was checked for systematic bias;
- reconciliation produces a fresh evidence digest;
- root cause and prevention action are recorded.

