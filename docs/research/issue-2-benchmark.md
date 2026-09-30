# Small local retrieval experiment: Issue #2

Executed on 2026-09-30, native Windows build 26200, Python 3.11.0, AMD Ryzen 7 9700X (8 cores/16 threads), approximately 31 GiB installed RAM, RTX 4060 8 GiB present. **Inference used CPU, four torch threads; CUDA/GPU performance was not measured.** This machine specification is not a measured minimum requirement.

[Machine-readable measurements and corpus hashes](issue-2-results.json), [upstream identities](issue-2-upstreams.json), [complete evaluation](issue-2-prior-art.md), [ADR](../adr/0001-reuse-audio-retrieval.md). Scripts live in `research/issue-2/`, expressly outside production architecture. Audio, SQLite, embeddings, model weights and raw traceback/cache files stay ignored.

## Corpus and inspection protocol

Eight original, deterministic synthetic fixtures, each 3 seconds, mono 48 kHz PCM16; approximately 2.3 MB total. No third-party samples or production assets. Generator uses seed `20260930`, NumPy synthesis and SciPy's existing `chirp`; no new DSP primitives. `01.wav` through `08.wav` are opaque names; descriptions in a sidecar manifest are **not** ingested as semantic hints. Auto-tags and keyword ranking are disabled for the SAS control (`AUTO_TAGS=0 SIM_WEIGHT=1 KW_WEIGHT=0`).

| File | Designed signal / qualitative target |
|---|---|
| 01.wav | Repeated 1 kHz electronic alert beeps |
| 02.wav | Ascending decaying three-note confirmation chime |
| 03.wav | Low saturated periodic buzzer |
| 04.wav | Broadband noise/hiss |
| 05.wav | Repeated decaying low swept kick-like impacts |
| 06.wav | Rising electronic sweep; whoosh proxy, not a recorded air whoosh |
| 07.wav | Steady low two-tone drone |
| 08.wav | Silence negative control |

Manual inspection here means the agent reviewed every query's ordered filenames and numeric scores against the designed fixture contents, checking expected classes, distractors, control and score direction. **No human listening study or audible quality judgment was performed.** The human audition validation remains a follow-up gate, not a claim made by this synthetic experiment. Targets were chosen before reading rankings; the first seven are basic class checks, and the eighth tests a game-role/negative-description failure mode. Multiple real-world assets can be valid answers, so these simple labels are not a substitute for DCASE-style human multi-relevance labels.

## What actually ran

| Candidate / boundary | Outcome |
|---|---|
| SAS pinned upstream `api/main.py` | Imported unmodified module, loaded real model, called `reindex_folder()` on all 8 files and `search(query, limit=3)` for all queries; SQLite populated; genuine Qdrant local client used. |
| LAION through Transformers | Real `laion/clap-htsat-unfused` audio/text feature extraction, model revision `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`, executed through SAS. No fake model or embeddings. |
| Qdrant | Genuine local cosine retrieval with real embedded fixtures; directly inspected raw `QdrantClient.search` output alongside upstream application output. No custom similarity/search implemented. Local mode replaces only server transport, not ranking/model behavior. |
| soundgrep missing-CLAP component control | Original `AudioEmbedder` spectral/random-text fallback + original `VectorIndex.add_batch/search` executed on all 8 files and queries. Separate processes isolate incompatible OpenMP runtimes. This is **not a valid semantic backend**. |
| soundgrep CLAP-enabled default | Installed `laion-clap==1.1.6`, invoked original embedder on fixture file list. Failed during checkpoint load: HTSAT-base requested, default checkpoint is HTSAT-tiny; no embeddings or semantic Top-N produced. Final isolated harness reproduces failure. |
| soundgrep integrated indexer | Actual `SampleIndexer.index_file` on 01.wav returned -1; `DatabaseManager must implement insert_sample()`; FAISS remained empty. Exact CLI DB call also raises missing `_conn`. No integrated ingestion success claimed. |
| Microsoft CLAP / DCASE / PAM / AudioCards / Freesound | Source/API/research evaluation only. No training/data downloads, no authenticated Freesound requests, no runtime ranking claims for these. |

The upstream model, DSP and ranking code was never patched. The experiment deliberately tests SAS's incorrect score transformation as-is. It does not deploy its Docker stack, Qdrant server, Gradio browser UI, uploads or incremental persistence workflow. soundgrep's isolated component test bypasses the `intelligence/__init__.py` imports of unrelated MIDI/effects/generation modules; this reduction is disclosed and is not evidence that the full application works.

## Exact reproduction (PowerShell)

Prerequisites: Git, Python 3.11 (or uv can select/install it), uv; network access for public source/packages/model downloads. GitHub CLI authentication is needed only for refreshing public repository metadata via `snapshot_sources.py`, not for retrieval. Run from repository root. No API keys required; do not provide Freesound credentials for this experiment.

```powershell
$evalRoot = Join-Path $env:TEMP 'audio-selector-issue2-reproduction'
git clone https://github.com/TaaroBravo/semantic-audio-search.git "$evalRoot/semantic-audio-search"
git -C "$evalRoot/semantic-audio-search" checkout 8e7e525b271cce19f19ac25e5340c576107f9d04
git clone https://github.com/fnsmdehip/soundgrep.git "$evalRoot/soundgrep"
git -C "$evalRoot/soundgrep" checkout bc2adf3e72b463f4899c51678aba08c8c17ea4a3

uv venv --python 3.11 .venv
uv pip sync --python .venv/Scripts/python.exe research/issue-2/environment.lock.txt
.venv/Scripts/python.exe research/issue-2/make_corpus.py
.venv/Scripts/python.exe research/issue-2/run_upstream.py sas --repo "$evalRoot/semantic-audio-search" --out artifacts/issue-2/sas
.venv/Scripts/python.exe research/issue-2/run_upstream.py sas --repo "$evalRoot/semantic-audio-search" --out artifacts/issue-2/sas-pinned
.venv/Scripts/python.exe research/issue-2/run_upstream.py soundgrep --repo "$evalRoot/soundgrep" --out artifacts/issue-2/soundgrep-isolated
.venv/Scripts/python.exe research/issue-2/probe_soundgrep_indexer.py --repo "$evalRoot/soundgrep"

uv venv --python 3.11 artifacts/soundgrep-clap/.venv
uv pip sync --python artifacts/soundgrep-clap/.venv/Scripts/python.exe research/issue-2/soundgrep-clap.lock.txt
artifacts/soundgrep-clap/.venv/Scripts/python.exe research/issue-2/run_upstream.py soundgrep --repo "$evalRoot/soundgrep" --out artifacts/issue-2/soundgrep-clap-isolated
# Expected exit 1: inspect result.json and stage-error.json for checkpoint mismatch.
```

Every run writes `result.json` under the specified ignored output folder. The model is pinned by default; `--model-revision` can explicitly change it for a separate run. Hugging Face cache resides outside tracked artifacts and can be reused; don't commit it. Raw UUIDs or absolute checkout paths are not stable result identities: compare filenames/hashes, score ordering and backend/model revision. Use a new output directory for clean SQLite state; local Qdrant state is in memory for each process.

`export_evidence.py` exports observed exception types and messages, without assigning a cause. Additional diagnostic lines are retained as `detail` (up to 1,000 characters, with `detail_truncated` when shortened); single-line errors omit `detail`. The checkpoint diagnosis in this report comes from manual source/error inspection, not a default applied to arbitrary failures. Check network, dependency, checkpoint and empty-message cases with `python -m unittest discover -s research/issue-2 -p test_export_evidence.py`.

The committed locks are `uv pip freeze` snapshots of the actual installed environments, including transitive dependencies, not hash-verified supply-chain lockfiles. `requirements.txt` documents important shared pins; reproduce with the full snapshot above. They are research environments with older upstream versions, not recommended production dependency baselines.

Original setup commands were `uv venv --python 3.11 .venv` and `uv pip install --python .venv/Scripts/python.exe` with the versions in requirements plus pydantic-settings/python-dotenv/rich/typer (see full lock). The direct CLAP environment used `uv pip install --python artifacts/soundgrep-clap/.venv/Scripts/python.exe laion-clap==1.1.6 faiss-cpu==1.8.0.post1 torch==2.3.1 torchaudio==2.3.1 torchvision==0.18.1 transformers==4.44.2`, then `mido==1.3.3` to investigate eager upstream package imports. The final isolated module harness does not require those unrelated features.

To refresh source/activity evidence, clone the other repositories listed in `snapshot_sources.py` into the matching sibling directories and run `python research/issue-2/snapshot_sources.py --clones <directory> --out <json-path>`. To reproduce the initial nonisolated soundgrep failures, use normal package imports of `soundgrep.intelligence.audio_embeddings.AudioEmbedder` and `soundgrep.db.vector.VectorIndex` in one process with the shared lock; the failures below explain why the final harness isolates them.

## Queries and Top-3 results

Order is left to right. Qdrant numbers are raw cosine (higher better). SAS numbers are its unmodified final `1 - cosine` under the controlled weights. **Do not compare SAS final score magnitude with cosine as the same metric.**

| Natural-language query | Qdrant raw Top-3 (file: cosine) | SAS upstream Top-3 (file: final score) |
|---|---|---|
| A high pitched electronic beep repeated several times | 01: .5050, 03: .2529, 04: .2463 | 04: .7537, 03: .7471, 01: .4950 |
| A bright ascending musical chime for a game confirmation | 02: .6264, 03: .2917, 01: .2323 | 01: .7677, 03: .7083, 02: .3736 |
| A low harsh buzzer for an error | 03: .4679, 01: .4601, 04: .3173 | 04: .6827, 01: .5399, 03: .5321 |
| The sound of white noise hissing | 04: .3031, 06: .1504, 02: .1328 | 02: .8672, 06: .8496, 04: .6969 |
| A deep kick drum hitting repeatedly | 05: .5591, 07: .2935, 01: .2501 | 01: .7499, 07: .7065, 05: .4409 |
| A rising electronic whoosh | 06: .4140, 04: .1942, 05: .1797 | 05: .8203, 04: .8058, 06: .5860 |
| A low steady ominous drone | 07: .3507, 03: .2191, 05: .1838 | 05: .8162, 03: .7809, 07: .6493 |
| A quiet interface confirmation without a harsh buzzer | 01: .3908, 06: .3454, 04: .3309 | 04: .6691, 06: .6546, 01: .6092 |

| Query (same order as above) | soundgrep missing-CLAP fallback Top-3 (file: score) |
|---|---|
| Beep | 04: .0698, 02: .0264, 06: .0251 |
| Chime | 07: .0238, 03: .0224, 05: .0208 |
| Buzzer | 04: .0828, 07: -.0117, 03: -.0161 |
| Hiss | 04: .0460, 06: -.0242, 08: -.0320 |
| Kick | 04: -.0208, 02: -.0268, 08: -.0281 |
| Whoosh proxy | 06: .1230, 01: .1210, 05: .1187 |
| Drone | 04: .0828, 07: -.0117, 03: -.0161 |
| Negative/role description | 03: .0340, 01: .0278, 02: .0238 |

Reference-audio fallback query 02.wav returned 02: 1.0000, 06: .9906, 01: .9895. A self-neighbor is expected but near-identical similarities to unlike signals show this DSP fallback is not evidence of good semantic audio similarity.

## Manual qualitative observations

1. **Basic retrieval infrastructure is viable.** LAION/Qdrant's intended generated class is first in all seven basic cases. Silence is not in these raw Top-3 lists. This is a tiny sanity check, not a general 100% accuracy claim. These fixtures are simple and highly separable.
2. **SAS fails at the application boundary.** In all seven basic queries, the expected fixture is demoted to third among the retrieved three. This exactly matches the cosine inversion inspected in `search()`. Labels/keyword leakage are disabled, so the issue cannot be explained away by filenames. The harness compares existing Qdrant search, not a custom corrected ranking implementation.
3. **Confusable alerts need role/context evaluation.** The buzzer query gives buzzer .4679 and beep .4601: a narrow margin despite the stronger separations for beep/chime. Raw semantic similarity alone does not establish correct UI role, length, loudness or annoyance.
4. **Negative language needs separate validation.** “Quiet interface confirmation without a harsh buzzer” ranks beep, sweep and hiss rather than the designed chime; it is not a reliable role profile or exclusion mechanism. No positive-minus-negative reranker is implemented in this gate.
5. **Fallback rankings must not be called semantic retrieval.** Buzzer and drone have identical results because their first four bytes are identical (“A lo”), which seed the fallback random text vector. Occasional class matches are chance, not model success. The failure is architectural even if some Top-N lists look plausible.
6. **Workflow work remains.** Neither application retains exact licensed original/preview provenance or supports a complete eligible-pool game-role/diversity/audition/export flow. These policies are the meaningful custom work; model/index/DSP primitives already exist.

## Setup friction, timings and incompatibilities

| Step | Observed cost / failure |
|---|---|
| Shared comparison environment | Resolve 11.56 s; package preparation/download 8 min 9 s; install 7.53 s; cold cache/network dominated. Windows Python default was 3.13, so explicitly selected 3.11 for upstream torch compatibility. |
| SAS cold model load | Setup/import/model download 210.56 s; indexing 8 files .913 s; complete run 212.86 s. HF checkpoint about 614.5 MB. |
| SAS cached, revision-pinned rerun | Setup 2.008 s; indexing .826 s; total 4.540 s; query measurements .021-.068 s including direct raw query and upstream query. Not an HTTP/UI latency benchmark. |
| Direct CLAP environment | Initial NumPy 1.26.4 request conflicts with PyPI laion-clap 1.1.6's exact NumPy 1.23.5 pin; separate env resolves it. Package prep 4 min 29 s; install 6.89 s. Source main's dependency metadata differs from PyPI. |
| soundgrep normal imports | Eager `intelligence/__init__.py` initially failed on missing mido; installing it proceeded to Windows OpenMP Error #15 (`libomp140` vs `libiomp5md`). No unsafe `KMP_DUPLICATE_LIB_OK` bypass used. |
| soundgrep isolated fallback | 8 audio/text embeddings plus reference in 1.992 s; FAISS add .000316 s; total 2.635 s; invalid semantic mode as explicitly marked in result. |
| soundgrep CLAP default | Cold attempt 360.81 s, downloads/tokenizers/checkpoint then `RuntimeError: Error(s) in loading state_dict for CLAP`; HTSAT-base/tiny size mismatch. The default fusion weight is about 1.864 GB and remains outside tracked files. Cached isolated retry about 9 s reproduces mismatch. No valid semantic rankings exist for this path. |
| soundgrep native indexer/CLI contract | Single-file indexer returned -1 with missing `insert_sample`; DB actually provides `add_sample`; CLI `_conn` absent. Vector method argument order and duration column names also disagree in source. |
| Windows HF cache | Symlink warning: cache works with copies on this machine; extra disk space possible. No administrator requirement for tested inference. |

GPU is optional for the successful measured route. Installation/model-download cost dominates the tiny workload; these timings do not estimate large-library throughput. Actual RSS/minimum RAM, persistent Qdrant server indexing, UI playback, incremental reindex, long BGM segmentation and real human relevance remain unmeasured. Source licenses and runtime package versions must be considered separately before distribution.

## Result for the architecture gate

Reuse LAION/Transformers embeddings and Qdrant; reuse standard DSP. Do not adopt either complete application unchanged. A bounded SAS UI fork remains plausible after ranking/filter/provenance fixes; soundgrep needs too many integration repairs to be the default. Custom implementation should concentrate on manifest/license evidence, role profiles, ranking composition, diversity policy, audition decisions and evaluation. The ADR commits to that reuse boundary while explicitly leaving production validation open.

## Validation of deliverables

- Regenerated corpus into a second ignored directory; all eight manifest hashes match exactly.
- Revision-pinned cached SAS run reproduced initial Top-3 filenames/scores; final process-isolated soundgrep harness reproduced recorded fallback rankings and CLAP mismatch.
- Compiled all research Python files and checked all local Markdown document links.
- `git diff --cached --check` passed. All 13 staged files are text artifacts; largest is under 30 KB. No staged WAV/MP3/FLAC, weights, databases, NumPy vectors or bytecode; credential-pattern scan found no tokens/private keys. `git check-ignore` confirms corpus, raw results and virtual environment are excluded.
- Scripts invoke existing embedding/index/DSP APIs only. No production semantic-search engine, perceptual metric or audio assets added; unrelated pre-existing untracked configuration was left untouched.
