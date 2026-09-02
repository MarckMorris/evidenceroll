# Why EvidenceRoll

**Decision:** build an evidence-aware progressive-delivery control plane for probabilistic
classification models whose ground truth arrives late.

## Direct answer

Progressive delivery for ordinary services asks whether the new revision is responding. Production
ML also has to ask whether the new decision function is safe, and that answer usually depends on
outcomes that arrive hours or weeks after inference. EvidenceRoll exists to make that waiting period
an explicit, blocking control-plane state instead of an implicit success.

## Evidence that the problem is real

Google's [ML Test Score](https://research.google/pubs/the-ml-test-score-a-rubric-for-ml-production-readiness-and-technical-debt-reduction/)
defines testing and monitoring as core production-readiness work and identifies needs that do not
exist in ordinary software testing.

A 2025 survey of 91 practitioners,
[Understanding Practitioners' Perspectives on Monitoring Machine Learning Systems](https://arxiv.org/html/2509.25195v1),
reports frequent performance degradation, latency and security problems. Participants described
monitor setup, threshold configuration, workload and alert fatigue as difficulties; requested
improvements included automated monitor setup, better performance/fairness monitoring, and automated
resolution or remediation guidance.

A peer-reviewed interview study of 18 ML engineers,
[“We Have No Idea How Models will Behave in Production until Production”](https://arxiv.org/html/2403.16795v1),
describes multi-stage evaluation plus continual monitoring and response as central MLOps work. Its
“velocity, visibility, versioning” framing favors a release controller that preserves what was
compared and why exposure moved.

Delayed outcomes are especially awkward. NannyML documents
[confidence-based performance estimation](https://nannyml.readthedocs.io/en/stable/how_it_works/performance_estimation.html)
when targets are absent, along with its calibration assumptions and limitations. This supports a
hybrid design: proxy signals can warn or hold; actual paired outcomes should remain the authority for
promotion when they become available.

## Why existing components do not make this redundant

| Component | What its current documentation provides | EvidenceRoll's boundary |
|---|---|---|
| [KServe 0.20](https://kserve.github.io/website/docs/model-serving/predictive-inference/rollout-strategies/canary) | inference revisions, traffic percentage, last-good/previous revision | decides whether evidence justifies changing exposure |
| [Argo Rollouts](https://argo-rollouts.readthedocs.io/en/stable/features/analysis/) | metric-driven proceed, pause and abort actions | supplies an ML-specific evidence verdict to Argo |
| [MLflow Registry](https://mlflow.org/docs/latest/ml/model-registry/tutorial/) | versions, metadata and champion/challenger aliases | evaluates one candidate change; does not replace identity/lineage |
| [Evidently](https://pypi.org/project/evidently/) | broad evaluations, tests and monitoring | can become a signal source; EvidenceRoll owns release state |
| [NannyML](https://nannyml.readthedocs.io/en/stable/how_it_works/performance_estimation.html) | estimated performance without labels | proxy estimation is evidence, not automatic permission to promote |

The conclusion that an integration gap exists is a design inference from these documented
boundaries, not a claim that no adjacent commercial or internal system exists.

## Alternatives considered

- **A generic end-to-end MLOps template.** Adds breadth but no thesis, and largely duplicates what
  KServe, MLflow and Argo already document.
- **A training/serving feature-contract gateway.** A real problem, but it guards inputs rather than
  the release decision, and it does not address delayed labels.
- **Model artifact supply-chain attestation.** Adjacent and valuable, yet mostly covered by existing
  signing and provenance tooling.
- **A GPU inference cost scheduler.** Cannot be demonstrated or verified without paid accelerator
  infrastructure.

The selected scope was the only one that both targets the delayed-evidence failure mode and can be
reproduced end to end on a laptop with no external account.

## Design consequence

The thesis is deliberately narrow: **unknown quality is a blocking state, not a successful state**.
From that follow the minimum sample, coverage, freshness, paired comparison, stage-specific windows,
explicit HOLD, immutable evidence digest, and audit-chain requirements.

## Limitations of this analysis

- Practitioner studies report experience; they do not quantify incident prevalence across all
  industries.
- Tool documentation establishes current documented behavior, not every possible extension.
- The synthetic benchmark validates specified controller behavior only; it is not evidence of
  real-world model or business validity.
