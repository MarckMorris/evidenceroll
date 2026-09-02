# Why EvidenceRoll

**Research date:** 2026-09-02  
**Decision:** build an evidence-aware progressive-delivery control plane for probabilistic
classification models with delayed ground truth.

## Direct answer

EvidenceRoll was selected because it addresses a current production-ML failure mode and fills a
visible gap in the target portfolio. The public portfolio already demonstrates Python, Kubernetes,
Terraform, database reliability, observability, security, and change-aware infrastructure gating.
Its public `mlops` repository was still introductory at the research date. A generic MLOps template
would add breadth without a thesis; a delayed-evidence release controller adds a defensible product
idea and exercises the missing model-lifecycle layer.

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
“velocity, visibility, versioning” framing strongly favors a release controller that preserves what
was compared and why it moved.

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

## Portfolio-value check

A current Paramount
[Lead Machine Learning Operations Engineer](https://careers.paramount.com/job/Burbank-Lead-Machine-Learning-Operations-Engineer-CA-91505/1397036200/)
posting explicitly asks for end-to-end ML observability, lineage, behavior-change and drift detection,
automated validation gates, shadow testing, canary strategies, rollback, delayed-label reasoning,
incident response, and reusable standards. EvidenceRoll creates inspectable code and operational
artifacts for those capabilities. One listing is not a labor-market survey; it is primary evidence
that this exact combination is valuable in a current senior role.

## Candidate comparison

Scores are judgment on a 1–10 scale. “Fit” reflects the public-portfolio gap; “proof” reflects whether
the claim can be reproduced without paid infrastructure.

| Candidate | Current pain | Portfolio fit | Differentiation | Local proof | Overall |
|---|---:|---:|---:|---:|---:|
| Evidence-aware rollout under delayed labels | 10 | 10 | 9 | 10 | **9.8** |
| Training/serving feature-contract gateway | 9 | 8 | 8 | 9 | 8.5 |
| Model artifact supply-chain attestation | 9 | 7 | 8 | 9 | 8.2 |
| GPU inference FinOps scheduler | 9 | 7 | 8 | 5 | 7.4 |
| Generic end-to-end MLOps template | 8 | 8 | 4 | 7 | 6.8 |

## Design consequence

The selected thesis is deliberately narrow: **unknown quality is a blocking state, not a successful
state**. From that follow the minimum sample, coverage, freshness, paired comparison, stage-specific
windows, explicit HOLD, immutable evidence digest, and audit-chain requirements.

## Limitations of the research

- Practitioner studies report experience; they do not quantify incident prevalence across all
  industries.
- Tool documentation establishes current documented behavior, not every possible extension.
- The job listing proves relevance for one employer and role, not demand frequency.
- Package and GitHub name searches found no exact `evidenceroll` match on the research date, but
  naming availability can change.
- The synthetic benchmark validates specified controller behavior only.

## Search stopping point

Research covered production-readiness literature, recent practitioner evidence, current first-party
tool capabilities, one detailed current role specification, adjacent project alternatives, naming,
and the target GitHub profile. It stopped after the problem, integration boundary, portfolio fit,
success criteria, and limitations were supported and further broad search was unlikely to change the
selection.

