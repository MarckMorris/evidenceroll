# Model card: synthetic acceptance fixtures

## Purpose

The bundled models exist only to exercise EvidenceRoll end to end without external services. They
are not intended for customer-churn decisions or any real-world use.

## Versions

- `champion`: logistic regression trained on a small sample and the first three features;
- `challenger-good`: logistic regression trained on the full synthetic training set and all features;
- `challenger-bad`: logistic regression trained on inverted synthetic labels to create a known
  regression failure.

All pipelines emit a positive-class probability. The registry records validation accuracy, Brier
score and ROC AUC plus a SHA-256 artifact digest.

## Features

`sessions_30d`, `avg_order_value`, `days_since_last_order`, `support_tickets`, and `discount_ratio`.
Names resemble retail concepts only to make the workflow understandable. Their distributions and
label equation are authored in
[`acceptance_fixtures.py`](../src/evidenceroll/acceptance_fixtures.py).

## Training and evaluation

Training uses deterministic seeds. A separate deterministic synthetic batch records manifest
metrics. Acceptance scenarios use different seeds. The good and bad challengers are not a model
benchmark; they are controlled inputs to a release-controller test.

## Limitations and prohibited use

- no real people, transactions or observed outcomes;
- no claim of representativeness, fairness, causal meaning or business value;
- no use for production scoring, targeting, eligibility, credit, employment, health or safety;
- joblib deserialization is limited to trusted local fixtures.
