"""Deterministic synthetic churn data used only by acceptance scenarios and tests."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FEATURE_NAMES = (
    "sessions_30d",
    "avg_order_value",
    "days_since_last_order",
    "support_tickets",
    "discount_ratio",
)


def generate_churn_batch(
    size: int,
    seed: int,
    covariate_shift: bool = False,
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Generate a transparent retail-churn classification acceptance fixture.

    This is a software-behaviour fixture, not a claim about real customer behaviour.
    """
    rng = np.random.default_rng(seed)
    sessions = np.clip(rng.normal(10.0, 4.0, size), 0.0, 40.0)
    order_value = np.clip(rng.lognormal(3.8, 0.45, size), 5.0, 500.0)
    recency = np.clip(rng.gamma(2.2, 9.0, size), 0.0, 180.0)
    tickets = np.clip(rng.poisson(1.3, size).astype(float), 0.0, 15.0)
    discount = np.clip(rng.beta(2.0, 5.0, size), 0.0, 1.0)

    if covariate_shift:
        recency = np.clip(recency + 55.0, 0.0, 365.0)
        tickets = np.clip(tickets + 4.0, 0.0, 20.0)
        discount = np.clip(discount + 0.35, 0.0, 1.0)

    linear = (
        -0.16 * (sessions - 10.0)
        - 0.008 * (order_value - 45.0)
        + 0.075 * (recency - 18.0)
        + 0.55 * (tickets - 1.0)
        + 2.2 * (discount - 0.28)
        - 0.7
    )
    probability = 1.0 / (1.0 + np.exp(-np.clip(linear, -20.0, 20.0)))
    labels = rng.binomial(1, probability).astype(np.int64)
    features = np.column_stack((sessions, order_value, recency, tickets, discount))
    return features.astype(np.float64), labels


def as_feature_dict(row: NDArray[np.float64]) -> dict[str, float]:
    return {name: float(value) for name, value in zip(FEATURE_NAMES, row, strict=True)}
