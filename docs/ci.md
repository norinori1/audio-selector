# CI validation

`Fast CI / Windows Python 3.11 regression` runs on every pull request and push
to `main`, including Draft PRs. It installs the Windows retrieval snapshot with
Python 3.11, checks dependency consistency and the submitted git change range,
then discovers all existing tests in `tests` and `research/issue-2`.
Existing tests cover manifest/license gating, ranking/diversity, frozen human-pilot
and role-metric reproduction, and audition HTTP/persistence/export/import.
The manifest eligibility and ranking config CLIs are also checked, and both
committed JSON Schemas must equal their respective CLI schema output. Validation
must leave tracked files unchanged; benchmark evidence is never regenerated.

## Frozen role-metric numerical reproduction

The `role-metrics-v1.json` reproduction gate permits absolute error **at most
`1e-15`**, with **zero relative tolerance**, only at these JSON paths:

- `results.<method>.<k>.per_query[<index>].intra_list_similarity`
- `results.<method>.<k>.mean_intra_list_similarity`

Here `<k>` is `1`, `3` or `5`. Both values must be finite JSON floats; `null`
must reproduce as `null` (for example, a one-item list has no pair similarity).
Keys, JSON types, list lengths/order and every other metric remain exact,
including Recall/mAP, paired/bootstrap results, integer diagnostics, labels and
signal hashes, package identity and ranking-config fingerprints. The complete
ranking JSON remains exactly equal to the frozen reference, including IDs,
candidate order, scores, eligibility and policy/contract metadata. The older
Issue #6 metrics retain their exact comparison.

These two fields average clipped float64 dot products of frozen 512-dimensional
vectors. NumPy/package version pins do not pin the CPU/SIMD-selected OpenBLAS
reduction kernel. In [Issue #21](https://github.com/norinori1/audio-selector/issues/21),
switching only Cooperlake to Zen in fresh Python processes, with four BLAS
threads, changed 76 diagnostic values by at most `1.1102230246251565e-16`;
rankings and all other metrics were identical. `1e-15` is a narrow empirical
rounding allowance (about nine times that observed maximum) for diagnostics on
the normalized `[0, 1]` similarity scale. It is not a general accuracy guarantee
for every numerical library, CPU or future dataset. A larger difference still
fails and requires investigation; the tolerance is never adjusted automatically.

The ordinary suite tests one-ULP variation at both allowed paths, the exact
tolerance boundary, and rejection of larger differences, non-finite values,
type/null/structure changes and changes to protected metrics, fingerprints,
IDs, candidate order and ranking scores. These controls run on every runner.
Actions continues to record the processor name and `np.show_runtime()` with
its selected BLAS architecture/thread count. No CPU kernel override is set in
CI; local kernel selection is a diagnostic control only on a host that supports
the required instructions. Frozen evidence and ranking calculations are unchanged.

## Expected skips

Fast CI permits exactly three skips, checked by full test ID **and reason**:

- `tests.test_retrieval.RetrievalIntegrationTests.test_real_batch_index_restart_query_reindex_gate_and_staleness`
  — `set AUDIO_SELECTOR_REAL_MODEL=1 for real CLAP/Qdrant Windows smoke`
- `tests.test_retrieval.RetrievalIntegrationTests.test_metadata_mismatch_persistent_build_reload_and_failed_rebuild`
  — `set AUDIO_SELECTOR_REAL_MODEL=1 for real CLAP/Qdrant Windows smoke`
- `tests.test_ranking.RankingIntegrationTests.test_real_signals_rank_eligible_pool_and_cli`
  — `set AUDIO_SELECTOR_REAL_MODEL=1 for real CLAP/Qdrant ranking smoke`

No research tests may skip. Missing role signals are an unexpected skip and fail
the audit. Missing real-model test IDs, empty discovery and expected failures also
fail. Update the explicit allowlist only when the integration-test contract changes.
Fast CI sets Hugging Face/Transformers offline mode and never intentionally loads
or downloads CLAP weights. The existing mocked model-failure test remains enabled.

## Local equivalents (PowerShell, Python 3.11, repository root)

```powershell
python -m pip install -r requirements-retrieval.lock.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
$env:PYTHONUTF8 = '1'
$env:AUDIO_SELECTOR_REAL_MODEL = '0'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
python scripts/ci_checks.py fast
python -m audio_selector.manifest benchmark/manifest.json --require-all-eligible
python -m audio_selector.ranking validate --config benchmark/roles/ranking-v1.json
git diff --check origin/main...HEAD
git diff --exit-code
```

`ci_checks.py` uses the same unittest discovery as
`python -m unittest discover -s tests -v` and
`python -m unittest discover -s research/issue-2 -v`, with the additional skip audit.
Actions checks PR base/head merge-base with full history; pushes check the event's
before/after range (an initial branch push checks the new commit).

## Manual real-model smoke

`Real Model Smoke / Windows Python 3.11 CLAP and Qdrant` has only
`workflow_dispatch`. From Actions, select **Real Model Smoke**, **Run workflow**
and the desired branch, or use:

```powershell
gh workflow run real-model-smoke.yml --repo norinori1/audio-selector --ref ci/issue-17-regression-gates-v1.0
```

GitHub [requires the dispatch workflow to exist on the default branch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow) before it
can be triggered. A new workflow on an unmerged Draft branch may therefore be
unavailable; a local smoke is separate evidence, not an Actions run.

Local equivalent after the same dependency install:

```powershell
$env:AUDIO_SELECTOR_REAL_MODEL = '1'
$env:HF_HUB_OFFLINE = '0'
$env:TRANSFORMERS_OFFLINE = '0'
python scripts/ci_checks.py heavy
```

Heavy runs all existing suites with **zero allowed skips**, including the actual
pinned CLAP audio/text embedding, Qdrant build/query/rebuild, offline CLI reload
in another process, changed/removed/blocked eligibility, and role-ranking tests.
Model/download/inference errors propagate as test/job failures; no fallback is
introduced. Its 60-minute limit allows a cold model download. The 25-minute Fast
CI limit includes package installation; model cost is kept separate from every PR.
There is no schedule and branch protection is not changed by these workflows.

## Cache and data policy

Both jobs cache public pip downloads using the dependency snapshot and
`pyproject.toml` hashes. Heavy also caches only the public Hugging Face `hub`
directory under a fresh runner temporary `HF_HOME`, keyed by OS, Python runtime,
dependency/project files and `audio_selector/contract.py` (model/revision identity).
There is no broad model-cache restore key. Indexes, audio, labels, selections,
credentials and other user files are excluded. No Actions artifacts are uploaded,
including model weights. Tests create temporary fixtures/indexes/exports and clean
them up. Cold-cache time and model-host availability remain operational risks.
