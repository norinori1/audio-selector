# Issue 7 evaluation protocol v1 (preregistered)

Written 2026-10-01 and committed with `benchmark/roles/ranking-v1.json` and
`benchmark/roles/query-roles-v1.json` **before any labeled evaluation run of the role
layer**. The commit that introduces this file is the preregistration point; results
are reported in a later commit and must use this protocol unchanged.

## What the author knew when freezing v1

- The Issue #6 report (`human-pilot-v1.md`): aggregate and per-query Recall@3
  tables, the named zero-recall queries (q01, q04, q05, q06), their first-positive
  ranks, and that the preregistered duration constraint improved some roles.
- Unlabeled score scales: per-query standard deviation of frozen query cosines
  (median about 0.15) and the corpus audio-audio centroid cosine distribution
  (off-diagonal mean 0.35, SD 0.25; one pair at 0.97).
- The author did **not** map anonymous clip IDs to candidates in the label file,
  inspect per-candidate labels, or listen to the corpus before freezing v1.

The pilot therefore motivated the feature families (role descriptions, soft
duration, negative descriptions, diversity). That makes any comparison on these
12 queries **in-sample with respect to design choices**, even though no parameter
is fitted to labels.

## Frozen configuration and how values were chosen

| Parameter | Value | Label-free rationale |
|---|---|---|
| `query` weight | 1.0 | The user request remains the reference signal |
| `role_positive` weight | 0.5 | Role knowledge is secondary (2:1) to the explicit request |
| `negative` weight | 0.5 | Symmetric with positives; applies only to the margin by which a negative description beats the request |
| `duration` weight | 0.15 | Median per-query SD of unlabeled semantic cosines: a clip one tolerance outside the preferred range loses about one typical spread |
| duration bounds | Issue #6 query bounds | Already preregistered in #6 `queries.json`; soft, 1 octave tolerance |
| MMR `diversity` | 0.25 | Relevance term about 2x the redundancy term in SD units (0.75 x 0.15 = 0.11 vs 0.25 x 0.25 = 0.06) |
| lineage cap | 1 | Derivatives of one original are one audition choice |
| pack cap | 3 of Top-5 | No single `acquisition_source` may fill the queue when alternatives exist |
| provider cap | 4 of Top-5 | Guarantees one slot from another provider when eligible candidates exist |
| near-duplicate cosine | 0.95 | Conventional near-identity level; set knowing one unlabeled pair exceeds it |
| DSP / metadata criteria | none | Supported by schema; no evidence justifies a DSP/metadata preference yet (ADR 0001 excludes quality scoring) |

No value was changed after computing any labeled metric for the role layer.

## Methods compared

1. `semantic_only` - order by recorded query cosine. Must reproduce the frozen
   Issue #6 `raw_semantic` ranking exactly (checked, tolerance 1e-5).
2. `semantic_role` - v1 role composition, exact-hash dedupe, no diversity stage.
3. `semantic_role_diversity` - v1 composition + pyversity MMR + group caps.

Predeclared exploratory ablations: no negative term; no role positives; no duration
term; duration only; role weights x0.5 and x2; MMR without caps; caps without MMR;
MMR diversity 0.1 and 0.5. They test sensitivity and are **never** used to select a
configuration. Issue #6's frozen hard-duration and first-segment methods are quoted
for reference only.

## Metrics

The exact Issue #6 convention via `benchmark_metrics.retrieval_metrics`: macro
Recall@K and truncated AP@K normalized by all R corpus positives, K = 1, 3, 5.
Plus unique-clip count reduction, projected playback-time reduction (counterfactual,
from logged per-clip listening time), first relevant rank, and Top-K diversity
diagnostics: unique packs/providers/lineages, duplicate-hash slots, maximum pack
share, and intra-list similarity (mean pairwise clipped centroid cosine).

## Evaluation method and claims allowed

Chosen method: **preregistered fixed interpretable weights, in-sample exploratory
comparison.** Leave-one-query-out or cross-validation would add nothing because no
parameter is estimated from labels; every fold would produce identical rankings.

Paired per-query deltas (wins/ties/losses, listed regressions) and a query-level
bootstrap 95% interval (10,000 resamples, seed 7) are reported for Recall/AP at
K = 3 and 5. With 12 correlated queries, one rater and 13 assets, intervals describe
this sample only.

Allowed: "on the Issue #6 pilot, v1 changed Recall@K by X (in-sample)". Not allowed:
generalized, held-out, or production superiority. That requires new labels on new
queries and/or corpus judged after this configuration is frozen.

## Reproduction

```powershell
# Model required once (labels are not read):
.venv/Scripts/python.exe -m audio_selector.role_evaluation collect --offline
# No model required:
.venv/Scripts/python.exe -m audio_selector.role_evaluation evaluate --out outputs/benchmark/role-metrics.json
```
