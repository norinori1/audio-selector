# Issue 7 validation

Windows 11, Python 3.11 venv from `requirements-retrieval.lock.txt` (+ `pyversity==0.2.0`),
pinned CLAP checkpoint loaded offline from the Hugging Face cache, Qdrant local mode.

## Commands run

```powershell
uv venv --python 3.11 .venv
uv pip sync --python .venv/Scripts/python.exe requirements-retrieval.lock.txt
uv pip install --python .venv/Scripts/python.exe -e . --no-deps
$env:HF_HUB_OFFLINE = '1'; $env:AUDIO_SELECTOR_REAL_MODEL = '1'
.venv/Scripts/python.exe -m unittest discover -s tests -v          # 40 tests, 0 skipped, OK
.venv/Scripts/python.exe -m unittest discover -s research/issue-2  # 5 tests, OK
.venv/Scripts/python.exe -m audio_selector.benchmark_metrics --labels benchmark/evaluation/human-labels-v1.json --out outputs/benchmark/reproduced-metrics.json
.venv/Scripts/python.exe -m audio_selector.role_evaluation collect --offline      # before labels were read
.venv/Scripts/python.exe -m audio_selector.role_evaluation evaluate --out benchmark/evaluation/role-metrics-v1.json --rankings-out benchmark/evaluation/role-rankings-v1.json
.venv/Scripts/python.exe -m audio_selector.retrieval build benchmark/manifest.json --index qdrant_storage/bench --offline
.venv/Scripts/python.exe -m audio_selector.ranking query benchmark/manifest.json --index qdrant_storage/bench --role ui-confirm --text "a bright short confirmation" --offline
```

## What was verified

| Requirement | Evidence |
|---|---|
| Role config data-driven and versioned | `ConfigTests`: schema/version/fingerprint; fingerprint changes with any weight; JSON Schema exported |
| Score contributions reproducible | `CompositionTests` (named terms sum to score); `test_committed_metrics_and_rankings_reproduce_without_model` recomputes all 12 rankings and 13 method/ablation metric sets from recorded signals and equals the committed JSON |
| Positive/negative separable; negation never excludes | Signals keep per-description cosines; `test_negative_description_is_soft_never_exclusion` |
| Eligibility cannot be overridden | `test_role_score_cannot_override_eligibility` (ineligible, review-required, missing, byte-mismatched decisions with maximal scores never ranked, for every diversity mode); `test_real_manifest_decision_binds_exact_bytes`; real-model test denies rights and re-ranks |
| Eligibility keys cannot enter role config | `test_eligibility_and_unknown_fields_cannot_enter_config` |
| Exact duplicates never repeated | `test_exact_duplicate_hash_never_occupies_two_slots` (all modes); frozen-ranking invariant test |
| Diversity constraints deterministic | caps/near-duplicate tests with input-order shuffling; library-trace test; `rank()` asserts each MMR explanation equals pyversity's gain |
| Human labels unchanged | `test_human_labels_are_unchanged` (raw-byte SHA-256 equals `run-metadata.json`) |
| Issue #6 metrics intact | `test_issue6_metrics_reproduce_exactly` (equals `metrics-v1.json`, hash checked); semantic-only baseline from new signals equals Issue #6 per-query metrics |
| Signal collection deterministic | A second `collect` into a fresh index produced identical signals (max vector difference 0.0) |
| Real adapter integration | `test_real_signals_rank_eligible_pool_and_cli`: real CLAP/Qdrant signals, blocked asset removed, new-process CLI query |

Anti-overfitting: config/protocol committed and pushed in `d353d26` before the labeled
evaluation; signals committed separately in `6b94777` without reading labels; one
evaluation run; results labeled in-sample/exploratory ([protocol](../../benchmark/evaluation/role-protocol-v1.md),
[results](../../benchmark/evaluation/role-results-v1.md)).

## Remaining risks

- v1 diversity caps regressed human-labeled Recall@5 by 16.7 pt in-sample; caps need held-out
  evaluation before being relied on. MMR-without-caps did not regress, but that is an ablation.
- Role composition gains are small, in-sample, and not statistically distinguishable from zero.
- 13 assets, one rater, two providers; footsteps and negation failures remain.
- `LocalIndex.query` re-inspects the index per description; acceptable for small corpora only.
