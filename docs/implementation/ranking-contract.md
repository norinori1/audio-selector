# Role ranking contract 1.0 (Issue #7)

ADR 0001 is retained. This layer composes signals produced by the pinned CLAP/Qdrant
adapter ([retrieval contract](retrieval-contract.md)) and orders an audition queue. It
trains nothing, adds no vector search and does not decide eligibility.

## Data flow

```text
manifest + policy --(manifest.evaluate)--> eligible pool inside Qdrant filters
request + role.positive --(LocalIndex.query, eligible only)--> union candidate pool (overfetch each)
request / positive / negative descriptions --(LocalIndex.query restricted to pool)--> raw cosines
LocalIndex.vectors --> stored segment vectors --> L2-normalized centroid per candidate
SoundFile --> duration / rate / channels / peak / RMS (observations)
          |
          v   rank(): pure function of recorded signals + config + eligibility decisions
eligibility re-check (bound to exact sha256) -> role score composition -> exact-hash dedupe
          -> [diversity enabled] pyversity MMR order -> lineage/pack/provider/near-duplicate caps
          -> top_n / beyond_top_n / suppressed / excluded, each with reasons
```

`rank_query()` collects signals, recomputes eligibility **after** collection and ranks.
`rank()` never touches the model or index, so recorded signals reproduce a ranking exactly.

## Separation of concerns

| Concern | Owner | Can a role score change it? |
|---|---|---|
| License / usage eligibility | `manifest.evaluate` + `Policy` | No. Ineligible, review-required, missing or byte-mismatched decisions are `excluded` (stage `eligibility`) before scoring. |
| Hard role constraint (optional) | `duration.mode = "hard"` | Excluded with stage `role-constraint`; this is fit, not permission. |
| Negative wording | `role.negative` | Never excludes. Only a bounded soft penalty. |
| Exact duplicates | invariant in `rank()` | Same original SHA-256 never occupies two positions; later copies are `suppressed`. Not configurable. |

The config model forbids unknown fields, so license/eligibility keys cannot be added to a role profile.

## Config schema `role-ranking/1.0`

JSON Schema: [ranking-config.schema.json](ranking-config.schema.json)
(`python -m audio_selector.ranking schema`). Benchmark instance:
[`benchmark/roles/ranking-v1.json`](../../benchmark/roles/ranking-v1.json). Consumer game
projects should keep their own profiles in their repositories.

| Field | Meaning |
|---|---|
| `config_id`, `version`, `notes` | Identity. Every result records these plus the canonical SHA-256 `fingerprint` of the parsed config. |
| `top_n`, `overfetch` | Queue length; eligible Top-K fetched per request/positive description to form the pool. |
| `default_weights` / `role.weights` | `query`, `role_positive`, `negative`, `duration` (non-negative). A role may override. |
| `role.positive` (>=1), `role.negative` | Separately encoded and separately reported descriptions. |
| `role.duration` | `min_seconds`/`max_seconds`, `tolerance_octaves`, `mode` soft/hard. |
| `role.dsp` | Optional soft ranges on `peak_dbfs`, `rms_dbfs`, `channels`, `sample_rate` (penalty `weight`). |
| `role.metadata` | Optional exact match on recorded manifest fields `provider`, `author`, `kind`, `media_type`, `acquisition_source`. |
| `diversity` | `enabled`, `algorithm` (`pyversity-mmr`), `diversity` in [0,1], `pack_key`, `max_per_lineage`, `max_per_pack`, `max_per_provider`, `near_duplicate_cosine` (each cap nullable). |

## Score composition

```text
semantic_query   = w.query * cos(request)
role_positive    = w.role_positive * mean_i cos(positive_i)
negative_penalty = -w.negative * max(0, max_j cos(negative_j) - cos(request))
duration         = -w.duration * (1 - duration_fit)      # fit 1 inside range, linear to 0 at tolerance octaves
dsp              = -sum(weight for each DSP criterion outside its range)
metadata         = +sum(weight for each metadata criterion that matches)
pre_diversity_score = sum of the above
```

Cosines are raw Qdrant cosine of the best segment (higher is more similar, never a probability).
Every result entry records the raw inputs (`signals`), each named `contributions` term,
`detail` (duration fit, negative margin, criteria hit), `pre_diversity_score` and `pre_diversity_rank`.

## Diversity implementation

- Library: [pyversity](https://github.com/Pringled/pyversity) **0.2.0**, MIT License
  (Copyright (c) 2025 Thomas van Dongen), numpy-only dependency, pinned in
  `requirements-retrieval.lock.txt`. Used unmodified through `pyversity.diversify(strategy=MMR)`.
- Algorithm: Maximal Marginal Relevance (Carbonell & Goldstein, SIGIR 1998):
  `gain = (1-d) * relevance - d * max_{selected} clip(cos, 0, 1)`, first item by relevance.
  Relevance is `pre_diversity_score`; similarity is the cosine of stored CLAP centroid vectors.
  Ties resolve by `(score desc, candidate_id)` input order; the library's `argmax` is deterministic.
- Each step records `step`, `marginal_gain`, `most_similar_prior`, `max_similarity_to_prior`.
  `rank()` re-derives the gain and raises if it disagrees with the library's score (tolerance 1e-4).
- Group constraints are applied while walking the MMR order until `top_n` items are accepted:
  lineage root, pack (`pack_key`, default `acquisition_source`, since the manifest has no pack
  field), provider, and near-duplicate cosine threshold. A violating item is `deferred` with
  every violated rule listed; it stays visible in `beyond_top_n`.
- MMR is computed over the whole deduplicated pool and constraints are applied afterwards, so
  a deferred item still counts in later MMR redundancy terms. This is deterministic and
  recorded; it is not a jointly constrained optimum.

## Result schema `role-ranking-result/1.0`

Top level: `query`, `role_id`, `ranking_config` (id, version, fingerprint, top_n, effective
weights, diversity policy, score formula), `diversity_implementation`, `retrieval_contract`
(model/revision/preprocessing), `index_state` (SHA-256 of the expected valid index payloads),
`eligibility_policy_version`, and the lists `top_n`, `beyond_top_n`, `suppressed`, `excluded`.
Ranked entries carry `rank`, `candidate_id`, `representation` (`original`), `sha256`,
`provider`, `author`, `pack`, `lineage_root`, `eligibility`, `signals`, `contributions`,
`detail`, `pre_diversity_score`, `pre_diversity_rank` and `reranking`
(`decision` selected/deferred/beyond-top-n/suppressed, `reasons`, `mmr`).

## Commands

```powershell
.venv/Scripts/python.exe -m audio_selector.ranking validate --config benchmark/roles/ranking-v1.json
.venv/Scripts/python.exe -m audio_selector.retrieval build benchmark/manifest.json --index qdrant_storage/bench
.venv/Scripts/python.exe -m audio_selector.ranking query benchmark/manifest.json --index qdrant_storage/bench --role ui-confirm --text "a bright short confirmation" --offline
```

## Limitations

Signal collection re-inspects the index per description (small-corpus adapter). Centroids
blur long multi-section BGM. Caps can starve a dominant provider/pack when the pool is
skewed; the v1 caps regressed human-labeled recall in the pilot ([results](../../benchmark/evaluation/role-results-v1.md)).
Weights are preregistered round values, not validated preferences. DSP values are
observations, not quality judgments; DSP/metadata criteria are unused in v1.
