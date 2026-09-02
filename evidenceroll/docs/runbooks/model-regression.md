# Runbook: model regression or rollback

## Trigger

- release stage becomes `rolled_back`;
- `ACCURACY_NON_INFERIORITY_FAILED`;
- `CALIBRATION_REGRESSION`;
- `CHALLENGER_LATENCY_BREACH` during canary;
- `FEATURE_DRIFT_BREACH` during canary.

## Immediate actions

1. Confirm `GET /v1/releases/{id}` reports zero challenger weight.
2. Verify `GET /v1/releases/{id}/audit-integrity` before exporting evidence.
3. Capture the evidence response, policy file and registry manifest.
4. Confirm the serving layer actually returned traffic to the champion; internal state alone is not
   enough when an external router is used.
5. Stop automatic retries of the same artifact/version.

## Diagnosis

- Compare the reason code with its exact threshold in the policy digest used by the event.
- Check label coverage and arrival bias before interpreting quality metrics.
- Slice failures by feature domain outside this reference implementation; do not lower the global
  threshold to hide one problematic segment.
- For PSI, inspect which feature shifted and whether the reference profile is still valid.
- For latency, separate network time, queueing and model execution at the endpoint.
- Confirm champion and challenger received the same preprocessing contract.

## Recovery

Create a new model version and a new release. Do not rewrite the rolled-back release or mutate its
evidence. Re-run shadow collection from zero because evidence is version- and stage-specific.

## Exit criteria

- champion serves all production traffic;
- audit chain is valid and head exported;
- failure is reproduced or bounded;
- corrective change has a new version;
- incident notes identify whether model, data, endpoint, label pipeline or policy caused the event.

