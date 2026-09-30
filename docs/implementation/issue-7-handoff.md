# Issue #7 Implementation Handoff

Issue: #7 — game-role scoring + diversity reranking composition

## Inputs

Treat these merged artifacts as authoritative inputs:

- ADR 0001
- Issue #4 manifest / eligibility contract
- Issue #5 pinned LAION/Transformers + Qdrant retrieval contract
- Issue #6 human relevance pilot:
  - `benchmark/evaluation/human-pilot-v1.md`
  - `benchmark/evaluation/human-labels-v1.json`
  - `benchmark/evaluation/metrics-v1.json`

The human pilot found that raw semantic Top-3 missed multiple role-specific positives, while simple duration constraints improved some roles. Negative wording was weak. These findings motivate transparent role policy; they do not justify a new model/vector DB.

## Objective

Implement a data-driven, inspectable game-role ranking composition layer and established diversity reranking around the existing retrieval system.

## Hard architecture boundaries

- Do not train or replace the embedding model.
- Do not implement a new vector search engine.
- Do not mix license eligibility with subjective role fit.
- Hard exclusions remain manifest/policy filters.
- Natural-language negation is never a hard exclusion.
- Reuse/wrap a documented MMR or equivalent established reranking algorithm where practical.
- Exact duplicate hashes must never occupy multiple Top-N slots.

## Role-profile contract

Role profiles must be versioned data, not scattered constants.

Support at minimum:

- one or more positive semantic descriptions;
- optional negative semantic descriptions as separately inspectable signals;
- duration preferences/constraints;
- verified metadata/basic DSP criteria where supported;
- configurable score weights;
- duplicate/source-pack/lineage diversity constraints;
- Top-K / overfetch configuration.

Every final result must expose score contributions and reranking reason.

## Human-pilot usage / anti-overfitting rule

The Issue #6 labels may be used to:
- identify failure modes;
- choose transparent feature families;
- verify calculations;
- compare configurations.

Do NOT tune arbitrary continuous weights against all 156 labels and then report the same in-sample score as evidence of general improvement.

Choose one defensible evaluation strategy and document it before reporting results, for example:

- preregistered/simple weights derived from role semantics rather than numerical optimization;
- leave-one-role/query-out evaluation;
- small cross-validation with strict separation;
- or clearly label any full-pilot result as exploratory/in-sample only.

No claim of production/generalized superiority without held-out evidence.

## Required comparisons

At minimum produce:

1. semantic-only baseline;
2. semantic + role composition;
3. semantic + role + diversity rerank.

Report:
- Recall@K;
- truncated mAP@K using the same Issue #6 convention;
- unique-source/pack/hash/lineage diversity diagnostics;
- candidate count / audition-cost proxy;
- per-query failure analysis.

Do not change Issue #6 labels.

## Acceptance focus

- data-driven role profiles;
- positive/negative signals separable;
- all score contributions inspectable;
- eligibility remains external;
- established diversity algorithm wrapped/reused;
- exact duplicates excluded;
- pack/source/lineage collapse configurable;
- ranking config versioned;
- comparative evaluation documented with honest in-sample/held-out labeling.

## Completion

Update the Draft PR with:
- config/schema;
- ranking architecture;
- chosen reranking implementation/license;
- evaluation methodology;
- comparative results;
- limitations;
- exact commands/tests.

Do not merge.