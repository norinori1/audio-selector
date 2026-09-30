# Issue 6: first human relevance pilot

Recorded 2026-09-30, following Phase A preparation in commit
`28be3f70a6503e889f5a1bc9e9263d3cc598385a`. User-supplied actual human labels
were evaluated; no judgments were generated or corrected by the assistant.
Issue #6 remains open and PR #12 remains Draft. This report completes the requested
result recording, not the entire human-dependent acceptance scope.

## Outcome

On this deliberately small corpus, full-segment semantic retrieval obtains
**Recall@3 45.62% and truncated mAP@3 0.4285**. The preregistered duration-constrained
comparison reaches **60.07% / 0.4711**; first-segment-only reaches **55.62% / 0.4618**.
Full-segment Top-3 misses all human-positive candidates on UI navigation, footsteps,
door interaction and portal/transition queries. At K=5 full-segment Recall rises to
66.32%, so increasing audition count helps but leaves relevant candidates uncovered.

These observations support work on transparent role/metadata constraints and
candidate coverage in Issue #7. They do not show that an alternative audio model or
vector database is necessary, or invalidate ADR 0001's reuse architecture. No weights,
prompts, corpus, segmentation or ranking were tuned after viewing the labels.

## Inputs and provenance

- One user-supplied labeling session: **156/156** query/candidate judgments,
  **36 relevant**, **120 irrelevant**, **0 unsure**; 13 candidates per query.
- Frozen package: `60ddd8ab1ae0b34911fb9d2838b3b154432826ccca897f03085ab835886a4f06`.
- Corpus: 13 unchanged originals, OpenGameArt 9 / UI SFX 4; 11 SFX and two BGM.
  All 13 remain eligible on report-time reevaluation of exact bytes/evidence.
- Same pinned CLAP/Qdrant predictions from Phase A: 36 derived segment vectors,
  12 queries, three methods. Model: `laion/clap-htsat-unfused` revision
  `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`.
- Source export `audition-labels.json` SHA-256:
  `54f14db1a60172341a646c3750a2677d866259dd5007f8eb2bfd7c07323e9f0c`. It agrees with the locally saved labels.
- Published anonymized relevance/playback fields: [human-labels-v1.json](human-labels-v1.json).
  Five free-text notes are omitted from the published input; the original remains
  local. Removing text does not change any computed metric. Artifact hashes,
  source hash and reproduction command are in [run-metadata.json](run-metadata.json).
- Complete computed results: [metrics-v1.json](metrics-v1.json).

The interface presented a complete corpus in per-query anonymous order independent
of model rank. Labels bind query/clip IDs to the frozen mapping. Source filenames
are not ground truth: the human's decisions are preserved even where they differ
from source descriptions. There is no second reviewer or inter-rater agreement test.

## Aggregate results

Recall and AP are macro-averaged across all 12 queries. All queries have at least
one positive, so no zero-positive queries are excluded in this run.

| Method | K | Recall@K | Truncated mAP@K | Unique-clip count reduction | Projected playback-time reduction |
|---|---:|---:|---:|---:|---:|
| Full-segment semantic | 1 | 33.96% | 0.3396 | 92.31% | 92.08% |
| Full-segment semantic | 3 | 45.62% | 0.4285 | 76.92% | 63.27% |
| Full-segment semantic | 5 | 66.32% | 0.5011 | 61.54% | 53.80% |
| Duration-constrained | 1 | 31.87% | 0.3187 | 92.31% | 92.98% |
| Duration-constrained | 3 | 60.07% | 0.4711 | 78.85% | 84.91% |
| Duration-constrained | 5 | 67.99% | 0.5231 | 67.31% | 81.42% |
| First-segment only | 1 | 33.96% | 0.3396 | 92.31% | 91.72% |
| First-segment only | 3 | 55.62% | 0.4618 | 76.92% | 80.23% |
| First-segment only | 5 | 67.99% | 0.5267 | 61.54% | 72.18% |

Recall@K = retrieved positives / all human-positive corpus candidates. Truncated
AP@K = sum of precision at positive retrieved ranks through K, divided by **all R
corpus positives**, not min(R,K). Implementation uses scikit-learn AP on retrieved
items scaled by retrieved-positive count / R. This convention caps AP by achieved
Recall and must be retained when comparing future reports; it is not a claim to
another library's differently normalized AP@K convention.

Count reduction compares each unique-candidate Top-K set with all 13 candidates.
The duration method can return fewer than K, particularly for BGM, which increases
its count reduction. Lower cost alone does not establish relevance or suitability.

## Per-query Recall@3

| Query | Role | Human positives | Full segments | Duration constrained | First segment |
|---|---|---:|---:|---:|---:|
| q01 | UI navigation | 5 | 0.00% | 40.00% | 20.00% |
| q02 | UI confirm | 8 | 37.50% | 37.50% | 37.50% |
| q03 | UI error | 4 | 25.00% | 25.00% | 25.00% |
| q04 | Movement / footsteps | 1 | 0.00% | 0.00% | 0.00% |
| q05 | Door interaction | 1 | 0.00% | 100.00% | 100.00% |
| q06 | Portal / transition | 3 | 0.00% | 33.33% | 0.00% |
| q07 | Stage clear | 2 | 100.00% | 100.00% | 100.00% |
| q08 | Electronic BGM | 1 | 100.00% | 100.00% | 100.00% |
| q09 | Guitar BGM | 1 | 100.00% | 100.00% | 100.00% |
| q10 | Pickup vs warning | 5 | 60.00% | 60.00% | 60.00% |
| q11 | Negative wording | 4 | 25.00% | 25.00% | 25.00% |
| q12 | Long BGM | 1 | 100.00% | 100.00% | 100.00% |

The four zero-recall full-segment queries are q01, q04, q05 and q06. In its full
ranking, the first human-positive candidate appears at ranks 4, 11, 5 and 5,
respectively. Duration constraints recover some navigation/portal candidates and
the door positive at K=3, but footsteps still has zero Recall@3 in all methods.
The negative-wording query q11 achieves only 25% Recall@3 in all methods; its
wording must not be interpreted as a reliable hard exclusion.

All methods retrieve the single positive at rank 1 for each of q08, q09 and q12.
This corpus therefore gives no relevance gain from full-segment coverage over the
first-segment ablation for the BGM queries. It does not justify adopting first-only
ingestion generally: only two BGM originals and three related prompts were tested.

## Human notes and effort limits

The five submitted notes give qualitative context: two describe mismatch/overstatement
for UI requests, one makes movement suitability depend on actor type, one identifies
a game-like transition, and one says a relevant stage-clear cue has weak impact.
These are summaries of the reviewer's comments, not assistant listening judgments.
They illustrate that semantic relevance and a useful in-game presentation are
different decisions. No systematic repeated-use fatigue score was collected.

Logged active playback totals **404.810 seconds (6.75 minutes)**
across **197 play starts**. This is player event time, not the reviewer's complete
session time: deliberation, navigation, note entry and breaks are not included.
The interface does not record seek offsets, so the logs cannot verify that the
reviewer auditioned the start, middle and end of every long track. Full-track or
repeated-use suitability therefore remains unestablished.

Projected time reduction applies each labeled clip's actual logged playback cost
to hypothetical Top-K sets. For full-segment K=3 it is 63.27%; duration-constrained
K=3 is 84.91%. **These are counterfactual projections, not measured realized or
causal time savings.** No separately timed exhaustive-versus-shortlist effort CSV
was provided. Memory/order effects and different replay behavior would require a
paired, controlled follow-up before claiming actual audition-time benefit.

## Reproduce and remaining work

From the repository root with the documented Windows environment:

```powershell
.venv/Scripts/python.exe -m audio_selector.benchmark_metrics --labels benchmark/evaluation/human-labels-v1.json --out outputs/benchmark/reproduced-metrics.json
```

The reproduced JSON must equal `benchmark/evaluation/metrics-v1.json`. No model
load/reindex is required for this calculation; it consumes the frozen predictions.
Report validation checked label completeness/package binding, exact corpus eligibility,
equality of raw-export and anonymized-input metrics, and benchmark protocol/metric tests.

Remaining work: diagnose missed role candidates; evaluate role/metadata/diversity
composition on held-out or newly labeled cases; collect systematic fatigue/game-fit
judgments where needed; and measure actual paired effort. This one-session,
13-asset pilot is not representative production validation. Shared-source/style bias,
correlated prompts, best-of-segment length bias and coarse segment boundaries remain.
CC0 evidence does not guarantee claim-free deployment or uploader authority.

No merge, Ready transition, Issue #6 closure or #7 preference-weight tuning is
performed by this report. The original Phase A human stop was respected; subsequent
user-supplied labels and this explicit report request are recorded as follow-up evidence.
