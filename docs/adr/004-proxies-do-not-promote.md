# ADR-004: Proxy metrics may block, but labels authorize promotion

**Status:** accepted  
**Date:** 2026-09-02

## Context

Feature PSI, confidence, and model disagreement are available immediately but do not directly
measure correctness or business harm. Label-free performance estimation also depends on assumptions
such as probability calibration.

## Decision

EvidenceRoll uses feature shift and disagreement as guardrails. A breach holds shadow traffic or
rolls back exposed canary traffic. Passing proxy thresholds is necessary but not sufficient:
promotion also requires labeled, paired non-inferiority and calibration evidence.

## Consequences

- The controller favors false holds over unsupported promotions.
- Long label delays make releases slower.
- Domain owners can extend the evidence engine, but changing authorization semantics requires a new
  policy ID and ADR.

