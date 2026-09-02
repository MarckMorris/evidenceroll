# Integrations

## Generic HTTP model

Create a production registry with the exact ordered feature contract. This command creates no
acceptance models and no synthetic profile:

```bash
python -m evidenceroll.cli registry-init \
  --registry .evidenceroll/registry \
  --feature amount \
  --feature merchant_risk \
  --feature account_age_days
```

Profile those features from an approved CSV as described below, then register champion and
challenger versions.

Register the endpoint:

```bash
python -m evidenceroll.cli register-endpoint candidate-42 \
  --provider generic_http \
  --endpoint https://model.internal/predict \
  --probability-field probability \
  --bearer-token-env MODEL_ENDPOINT_TOKEN
```

EvidenceRoll sends:

```json
{
  "instances": [
    {
      "sessions_30d": 8.0,
      "avg_order_value": 55.0,
      "days_since_last_order": 21.0,
      "support_tickets": 2.0,
      "discount_ratio": 0.25
    }
  ]
}
```

Accepted response forms are `{"probability": 0.72}` or `{"probability": [0.72]}`. The field name is
configurable. Values outside `[0,1]`, non-numeric values, timeouts, and non-success HTTP responses fail
the prediction request.

## KServe V2

```bash
python -m evidenceroll.cli register-endpoint candidate-42 \
  --provider kserve_v2 \
  --endpoint https://model.internal/v2/models/candidate-42/infer \
  --input-name predict \
  --output-name probabilities \
  --bearer-token-env MODEL_ENDPOINT_TOKEN
```

EvidenceRoll sends one `FP64` input tensor with shape `[1, feature_count]` and reads the configured
output tensor. If the first output element is a class-probability vector, the final element is treated
as the positive-class probability. Feature names and order come from `manifest.json`; prediction
requests with missing or unexpected features fail closed.

## Credential handling

Registry metadata stores only `bearer_token_env`, never the token. Inject the named variable with a
secret manager. Rotating the environment value does not change the registry manifest.

`EVIDENCEROLL_API_KEY` protects mutation endpoints with `X-EvidenceRoll-Key`. Put TLS and
identity-aware authorization at the ingress/service mesh; the built-in key is a minimal deployment
guard, not multi-tenant IAM.

## Reference profiling

Build the production-shift baseline from an approved CSV snapshot. The file must contain every
feature from `manifest.json`; additional columns are ignored. Values must be finite numbers.

```bash
python -m evidenceroll.cli profile-reference approved-reference.csv \
  --registry .evidenceroll/registry \
  --min-rows 1000
```

The command writes quantile bins plus the input row count and SHA-256 digest. It does not copy raw
reference rows into the registry. Treat the source digest as lineage metadata, not as proof that the
dataset was approved.

## Argo Rollouts

`GET /v1/argo/releases/{release_id}/analysis` returns:

```json
{
  "status": "Inconclusive",
  "action": "hold",
  "evidence_digest": "...",
  "reason_codes": ["INSUFFICIENT_LABELS"]
}
```

Mapping:

| EvidenceRoll action | Argo-facing status |
|---|---|
| `HOLD` | `Inconclusive` |
| `START_CANARY` | `Successful` |
| `PROMOTE` | `Successful` |
| `ROLLBACK` | `Failed` |

Apply [`deploy/kubernetes/argo-analysis-template.yaml`](../deploy/kubernetes/argo-analysis-template.yaml)
after Argo Rollouts is installed. Verify the exact web-provider schema against the Argo version in
your cluster because CRDs evolve independently from EvidenceRoll.

## Prometheus and Grafana

The `/metrics` endpoint includes:

- `evidenceroll_predictions_total`;
- `evidenceroll_feedback_total`;
- `evidenceroll_decisions_total`;
- `evidenceroll_model_inference_seconds`;
- `evidenceroll_release_stage`;
- `evidenceroll_label_coverage_ratio`;
- `evidenceroll_max_feature_psi`.

Compose provisions Prometheus rules and a Grafana dashboard. Kubernetes uses standard scrape
annotations; adapt them to a `ServiceMonitor` if the cluster uses Prometheus Operator.

## Registering external endpoints safely

1. Run `registry-init` to establish the exact ordered feature contract.
2. Run `profile-reference` against approved training/reference data under your data-governance
   process.
3. Register champion and challenger endpoint versions.
4. Set endpoint credentials through the runtime secret provider.
5. Replay a known traffic window and calibrate policy thresholds.
6. Create a shadow release.
7. Verify prediction/feedback coverage and audit-chain export.
8. Only then connect the Argo analysis gate or automatic reconciliation loop.

Do not enable automatic promotion using the example profile or thresholds on real traffic.
