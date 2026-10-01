# Issue #17 CI Implementation Handoff

Issue: #17 — PR regression gate + real-model smoke workflow

## Objective

Add CI for the existing #4–#8 audio-selector pipeline without making every PR pay the cost of downloading/running the full CLAP checkpoint.

Implement two workflows:

1. fast PR regression gate;
2. manual heavy real-model smoke.

Do not change production behavior merely to satisfy CI.

## Repository assumptions

- Primary supported development platform is Windows.
- Python 3.11 is the exercised runtime.
- Retrieval dependencies are pinned in the repository.
- Real-model tests are guarded by `AUDIO_SELECTOR_REAL_MODEL=1`.
- Public CLAP checkpoint/model identity is pinned by the retrieval contract.
- Existing tests already cover manifest/license gating, Qdrant retrieval, human-pilot metric reproduction, role ranking/diversity, and audition/export behavior.

Read before implementation:

- `README.md`
- `docs/adr/0001-reuse-audio-retrieval.md`
- `docs/implementation/manifest-contract.md`
- `docs/implementation/retrieval-contract.md`
- `docs/implementation/ranking-contract.md`
- `docs/implementation/audition-contract.md`
- Issue #17

## Workflow A — Fast PR CI

Suggested path:

`.github/workflows/ci.yml`

Triggers:

- `pull_request`
- `push` to `main`

Required environment:

- `windows-latest`
- Python 3.11

Use concurrency cancellation so an outdated run for the same PR/branch does not continue consuming runner time.

Set a reasonable timeout.

### Install

Prefer the repository's pinned dependency snapshot / existing reproducible Windows setup.

Install enough dependencies for the ordinary suite, ranking/evaluation tests, and audition/export tests.

Do not intentionally download the CLAP model checkpoint in this workflow.

### Test behavior

Run the ordinary suite with real-model-only tests skipped.

The workflow must distinguish intentional real-model skips from unexpected skips. Do not simply accept arbitrary test skipping.

At minimum run:

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s research/issue-2 -v
```

Use the repository's actual Python path/venv strategy as appropriate.

Also validate committed configs/schemas/artifacts with existing CLIs/tests where this adds coverage without duplicating the entire suite.

Examples to inspect and include when meaningful:

- manifest validation;
- ranking config validation;
- benchmark/evaluation reproduction;
- audition/export roundtrip tests.

Do not regenerate and overwrite committed benchmark outputs.

### Diff hygiene

Check whitespace errors across the PR change range, not merely the runner working tree.

Use a robust base-aware command with full-enough git history, e.g. fetch-depth 0 and compare against the PR base / main merge-base.

The exact implementation may differ, but `git diff --check` must actually inspect the submitted changes.

## Workflow B — Heavy real-model smoke

Suggested path:

`.github/workflows/real-model-smoke.yml`

Initial trigger:

- `workflow_dispatch`

Do not add a schedule yet.

Environment:

- `windows-latest`
- Python 3.11
- `AUDIO_SELECTOR_REAL_MODEL=1`

Run the real model/checkpoint path. Model download or inference failure must fail the job; never add fake/random fallback behavior.

Exercise the existing real-model integration tests, including:

- CLAP checkpoint/model load;
- audio/text embeddings;
- Qdrant build/query;
- restart/persistence path where existing tests support it;
- eligibility removal/blocking regression;
- real role-ranking integration.

Prefer reusing current test entry points instead of writing CI-only duplicate integration logic.

## Caching

Cache public package/model downloads only when safe and useful.

Cache keys must account for relevant dependency/checkpoint identity.

Never cache/upload:

- private/user audio;
- uncommitted human labels;
- secrets;
- arbitrary local selection exports;
- user filesystem paths.

Do not upload the model checkpoint as a workflow artifact.

## Security / permissions

Use minimum GitHub Actions permissions.

The workflows only need repository checkout/read unless a concrete check requires more.

Do not add secrets or credentials for the current public-model smoke.

## Validation before completion

Validate workflow syntax and, where possible, execute local equivalents of every command.

Check that:

- normal CI does not instantiate/download the real model;
- expected real-model skips are the only skips;
- heavy workflow enables and executes the real-model tests;
- dependency/cache paths work on Windows;
- no generated caches/audio/model binaries are staged;
- CI does not mutate committed benchmark evidence;
- workflow failure propagates correctly.

If GitHub Actions can be run on the Draft PR, inspect actual run results and fix workflow-specific failures rather than declaring success from YAML inspection alone.

## Documentation

Add concise CI documentation covering:

- Fast CI contents;
- expected skips;
- manual real-model workflow launch;
- local equivalents;
- cache policy;
- why heavy real-model smoke is not required on every PR.

## Completion report

Update Draft PR with:

- starting SHA;
- final SHA;
- workflow files;
- exact jobs/checks;
- actual GitHub Actions run URLs/results if available;
- local validation;
- expected skips;
- heavy workflow runtime/cache observations if run;
- unresolved risks.

Keep PR Draft.

Do not merge.
