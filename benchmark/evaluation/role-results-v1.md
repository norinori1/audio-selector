# Issue 7: role composition and diversity results v1

Recorded 2026-10-01. **In-sample, exploratory results** from the preregistered protocol in
[role-protocol-v1.md](role-protocol-v1.md). The configuration was committed and pushed in
`d353d26aa7d1f6b66c29c3a13b04486c958ef08b` before any labeled role evaluation. Signals were
recorded in a separate commit without reading labels. The labeled evaluation was run once;
no configuration value was changed afterwards. Issue #6 labels are unchanged
(SHA-256 `3293948d…5f49`, 156 judgments, 36 relevant).

## Outcome

- **Role composition (v1) gives a small in-sample gain at K=3**: Recall@3 45.62% -> 48.96%,
  mAP@3 0.4285 -> 0.4618, mAP@5 0.5011 -> 0.5288. Only q01 changes Recall@3 (0 -> 2 of 5
  navigation positives). Recall@5 is flat (66.32% -> 65.90%, q03 regresses). All
  bootstrap intervals include zero. This is not evidence of generalized improvement.
- **The preregistered diversity stage regresses relevance**: Recall@5 66.32% -> 49.58%
  (-16.74 pt, 95% bootstrap CI [-36.1, -1.3] pt; 5 queries worse, 1 better). It improves
  the numerical diversity proxies (providers 1.75 -> 2.00, max pack share 0.500 -> 0.433,
  intra-list similarity 0.445 -> 0.409 at K=5) but the human-labeled usefulness proxy
  falls. On this pilot, v1 diversity did **not** improve audition usefulness.
- The semantic-only baseline recomputed from recorded signals reproduces Issue #6
  `raw_semantic` exactly (order, cosines within 1e-5, every per-query metric).

## Primary comparison

Macro means over 12 queries, Issue #6 metric convention (truncated AP normalized by all R
positives). Count/time reductions are against all 13 candidates; time is a counterfactual
projection from logged listening, not measured savings. Packs = unique `acquisition_source`;
ILS = mean pairwise clipped centroid cosine in Top-K; first relevant rank uses the full ordering.

| Method | K | Recall@K | mAP@K | Count red. | Proj. time red. | Packs | Providers | Max pack share | ILS | 1st relevant rank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| semantic_only | 1 | 33.96% | 0.3396 | 92.31% | 92.08% | 1.00 | 1.00 | 1.000 | - | 2.92 |
| semantic_only | 3 | 45.62% | 0.4285 | 76.92% | 63.27% | 2.58 | 1.50 | 0.472 | 0.445 | 2.92 |
| semantic_only | 5 | 66.32% | 0.5011 | 61.54% | 53.80% | 3.58 | 1.75 | 0.450 | 0.438 | 2.92 |
| semantic_role | 1 | 33.96% | 0.3396 | 92.31% | 92.71% | 1.00 | 1.00 | 1.000 | - | 2.67 |
| semantic_role | 3 | 48.96% | 0.4618 | 76.92% | 81.19% | 2.50 | 1.50 | 0.500 | 0.472 | 2.67 |
| semantic_role | 5 | 65.90% | 0.5288 | 61.54% | 71.45% | 3.25 | 1.75 | 0.500 | 0.445 | 2.67 |
| semantic_role_diversity | 1 | 33.96% | 0.3396 | 92.31% | 92.71% | 1.00 | 1.00 | 1.000 | - | 3.00 |
| semantic_role_diversity | 3 | 44.79% | 0.4201 | 76.92% | 81.76% | 2.42 | 1.58 | 0.528 | 0.374 | 3.00 |
| semantic_role_diversity | 5 | 49.58% | 0.4510 | 61.54% | 71.60% | 3.50 | 2.00 | 0.433 | 0.409 | 3.00 |

Duplicate-hash slots are 0 for every method (the corpus has no exact duplicates; the
invariant is exercised by unit tests). Unique lineages equal K for every method (no
derivatives in this corpus). Reference Issue #6 frozen methods: hard duration constraint
60.07% / 0.4711 at K=3 and 67.99% / 0.5231 at K=5; first-segment 55.62% / 0.4618 and
67.99% / 0.5267.

The higher projected time reduction of the role methods mainly reflects the soft duration
term moving long BGM out of SFX shortlists; it is a counterfactual, not a relevance gain.

## Per-query results and failure analysis

| Query | R | Semantic R@3 | Role R@3 | Role+div R@3 | Semantic R@5 | Role R@5 | Role+div R@5 | 1st rel. rank S / R / D |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| q01 UI navigation | 5 | 0.00% | 40.00% | 40.00% | 40.00% | 60.00% | 60.00% | 4 / 2 / 2 |
| q02 UI confirm | 8 | 37.50% | 37.50% | 37.50% | 62.50% | 62.50% | 50.00% | 1 / 1 / 1 |
| q03 UI error | 4 | 25.00% | 25.00% | 25.00% | 50.00% | 25.00% | 25.00% | 1 / 1 / 1 |
| q04 Footsteps | 1 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 11 / 12 / 12 |
| q05 Door | 1 | 0.00% | 0.00% | 0.00% | 100.00% | 100.00% | 0.00% | 5 / 4 / 6 |
| q06 Portal | 3 | 0.00% | 0.00% | 0.00% | 33.33% | 33.33% | 0.00% | 5 / 4 / 6 |
| q07 Stage clear | 2 | 100.00% | 100.00% | 50.00% | 100.00% | 100.00% | 50.00% | 1 / 1 / 1 |
| q08 Electronic BGM | 1 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 1 / 1 / 1 |
| q09 Guitar BGM | 1 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 1 / 1 / 1 |
| q10 Pickup vs warning | 5 | 60.00% | 60.00% | 60.00% | 60.00% | 60.00% | 60.00% | 1 / 1 / 1 |
| q11 Negative wording | 4 | 25.00% | 25.00% | 25.00% | 50.00% | 50.00% | 50.00% | 3 / 3 / 3 |
| q12 Long BGM | 1 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 1 / 1 / 1 |

Regressions, read from the recorded score breakdowns in [role-rankings-v1.json](role-rankings-v1.json):

- **Near-duplicate cap deferred human positives (q02, q07; q10 affected in ordering).**
  `uisfx-success` and `uisfx-level-up` have centroid cosine 0.9659 >= 0.95. The reviewer
  judged both relevant for q07 and q02, so deferring one is a pure relevance loss here.
  Whether auditioning both is wasteful is a taste/fatigue question this pilot did not measure.
- **Provider cap starved the dominant provider (q05, q06).** 9 of 13 assets are OpenGameArt.
  Cap 4 forced a UI SFX item into door/portal queues and deferred the OpenGameArt door
  and portal positives to rank 6.
- **Soft duration too weak for long BGM in SFX roles (q05, q06).** A 0.15 maximum penalty
  left 60+ second BGM with the highest raw request cosine in SFX Top-5s. Issue #6's hard
  filter removes them; soft v1 demotes but does not remove them.
- **Role composition moved a q03 positive from rank 4 to rank 7** (Recall@5 50% -> 25%);
  it (`uisfx-level-up`) was overtaken by `oga-menu-select` and `oga-menu-move` under the
  composed score.
- **q04 footsteps is unsolved by every signal.** The single human positive ranks 11th-12th.
  The file named for footsteps is not that positive; the pilot notes say movement fit
  depends on actor type. No composition of these semantic signals addresses this.
- **q11 negation remains weak** (Recall@3 25% for all methods). Separately scored negative
  descriptions did not change Recall@3, consistent with ADR 0001's warning.

Improvements: q01 (navigation positives from rank 4 to rank 2), and q05/q06 first positives
rank 5 -> 4 under role composition (AP@5 gains).

## Paired comparisons (query-level bootstrap, 10,000 resamples, seed 7)

| Comparison | Metric | Mean delta | Bootstrap 95% CI | W/T/L | Regressions |
|---|---|---:|---|---|---|
| semantic_role vs semantic_only | recall@3 | +0.0333 | [+0.0000, +0.1000] | 1/11/0 | - |
| semantic_role vs semantic_only | ap@3 | +0.0333 | [+0.0000, +0.0806] | 2/10/0 | - |
| semantic_role vs semantic_only | recall@5 | -0.0042 | [-0.0625, +0.0500] | 1/10/1 | q03 |
| semantic_role vs semantic_only | ap@5 | +0.0276 | [-0.0167, +0.0775] | 4/7/1 | q03 |
| semantic_role_diversity vs semantic_only | recall@3 | -0.0083 | [-0.1250, +0.1000] | 1/10/1 | q07 |
| semantic_role_diversity vs semantic_only | ap@3 | -0.0083 | [-0.0833, +0.0583] | 1/10/1 | q07 |
| semantic_role_diversity vs semantic_only | recall@5 | -0.1674 | [-0.3611, -0.0125] | 1/6/5 | q02, q03, q05, q06, q07 |
| semantic_role_diversity vs semantic_only | ap@5 | -0.0501 | [-0.1278, +0.0206] | 2/5/5 | q02, q03, q05, q06, q07 |
| semantic_role_diversity vs semantic_role | recall@3 | -0.0417 | [-0.1250, +0.0000] | 0/11/1 | q07 |
| semantic_role_diversity vs semantic_role | ap@3 | -0.0417 | [-0.1250, +0.0000] | 0/11/1 | q07 |
| semantic_role_diversity vs semantic_role | recall@5 | -0.1632 | [-0.3472, -0.0208] | 0/8/4 | q02, q05, q06, q07 |
| semantic_role_diversity vs semantic_role | ap@5 | -0.0778 | [-0.1750, -0.0083] | 1/7/4 | q02, q05, q06, q07 |

Twelve correlated queries, one rater and 13 assets: intervals describe this sample only.

## Predeclared ablations (exploratory; not used to choose a configuration)

| Ablation | R@3 | mAP@3 | R@5 | mAP@5 |
|---|---:|---:|---:|---:|
| no negative term | 48.96% | 0.4618 | 57.99% | 0.5049 |
| no role positives | 57.29% | 0.4896 | 65.90% | 0.5403 |
| no duration term | 47.29% | 0.4479 | 65.90% | 0.5190 |
| duration only | 48.96% | 0.4479 | 67.99% | 0.5264 |
| role weights x0.5 | 47.29% | 0.4507 | 65.90% | 0.5281 |
| role weights x2 | 60.07% | 0.5127 | 64.86% | 0.5440 |
| MMR without caps | 48.96% | 0.4479 | 67.57% | 0.5281 |
| caps without MMR | 43.12% | 0.4035 | 60.69% | 0.4721 |
| MMR diversity 0.1 | 43.12% | 0.4035 | 60.69% | 0.4746 |
| MMR diversity 0.5 | 40.00% | 0.3882 | 46.94% | 0.4165 |

Hypotheses for a future held-out test, **not conclusions**: the group caps (not MMR itself)
drive the diversity regression; role positive descriptions may hurt K=3 while the
negative term helps K=5; stronger duration weighting may help. Choosing any of these from
this table and reporting it on the same labels would be the in-sample tuning the protocol
forbids. A v2 configuration needs new labels judged after it is frozen.

## Artifacts and reproduction

| Artifact | SHA-256 |
|---|---|
| [role-signals-v1.json](role-signals-v1.json) | `f72e87644a099314025c87eda91f9c3a8ee4b926cb42583e0c0743efbef249ab` |
| [role-metrics-v1.json](role-metrics-v1.json) | `d1200ff1be3d72592baaaaf8d1f268cb4c6c4a731be6723bd3d41f123035e0bb` |
| [role-rankings-v1.json](role-rankings-v1.json) | `082198f850aa5ba2ade6c5787dfad01dd102124848271fe878b3e7a4c067cadb` |
| config `benchmark-game-roles` 1.0.0 | canonical fingerprint `cfddc574c441742174399c5eeeab59084cf274009004d7caa4797a7826a7975e` |

```powershell
.venv/Scripts/python.exe -m audio_selector.role_evaluation evaluate --out outputs/benchmark/role-metrics.json --rankings-out outputs/benchmark/role-rankings.json
```

Output equals the committed JSON (tested). Re-collecting signals from a fresh index
(`collect --offline`) reproduced every recorded signal bit-for-bit on the development machine.

## Limitations

In-sample with respect to feature-family design; one rater; 13 CC0 assets from two
providers, 11 SFX and 2 BGM; correlated prompts; centroid vectors blur long BGM; soft
duration and caps interact with a provider-skewed corpus. The benchmark profiles are data
for this corpus, not recommended production profiles. No claim of production or
generalized superiority is made.
