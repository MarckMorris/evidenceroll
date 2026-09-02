# Data card: synthetic churn-like fixtures

## Summary

EvidenceRoll generates all acceptance data locally with NumPy. No dataset is downloaded and no
personal information is present.

## Generation

Five numeric features are sampled from clipped normal, lognormal, gamma, Poisson and beta
distributions. A documented logistic equation produces a probability; a seeded Bernoulli draw
produces the binary label.

The `covariate-shift` scenario adds a large shift to recency, support tickets and discount ratio.
The shift is intentionally obvious so the PSI policy path is deterministic.

## Intended use

- exercising prediction/feedback contracts;
- testing paired metrics and late-label joins;
- verifying hold, canary, promote and rollback transitions;
- demonstrating drift-warning behavior.

## Non-intended use

This data must not be used to infer real churn behavior, compare learning algorithms, choose a
business threshold, or claim fairness. It contains no protected attributes and cannot validate a
fairness-monitoring system.

