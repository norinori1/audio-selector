# HUMAN AUDITION REQUIRED

Issue #6 **Phase A only**, Draft PR #12. Human relevance and game suitability have
not been measured. No human labels, preferences, metrics or weight tuning exist.

## Launch on Windows

From the repository root on `agent/issue-6-human-benchmark-prep-v1.0`:

```powershell
# On a fresh checkout (the audio and prepared package are committed):
uv venv --python 3.11 .venv
uv pip sync --python .venv/Scripts/python.exe requirements-retrieval.lock.txt
uv pip install --python .venv/Scripts/python.exe -e . --no-deps

.venv/Scripts/python.exe -m audio_selector.manifest benchmark/manifest.json --require-all-eligible
.venv/Scripts/python.exe -m audio_selector.audition
```

Open **http://127.0.0.1:8765** in Chrome or Edge. Launch requires no model download
or indexing. If port 8765 is occupied, add `--port 8766` and open the printed URL.
Ctrl+C stops the server. Use the exact 127.0.0.1 address for saved-label requests.

Listen and decide **Relevant / Not relevant / Unsure** for each anonymous clip.
Several clips can be relevant, and a query may have no positives. Relevance means
matching the requested sound. Record perceived fit, repeated-use fatigue, aesthetic
mismatch, semantically matching but unusable sounds, and wording-induced false
positives in optional notes. Those are human decisions, separate from retrieval.
Revisit Unsure before evaluation. Long tracks have start/middle/end 10-second
buttons plus unrestricted original-track playback; check all three portions.

There are **13 unique originals × 12 requests = 156 relevance judgments**. This
complete-corpus pool avoids unknown relevant assets outside a model's Top-K and
allows multiple-positive Recall. Short SFX plus three 10-second portions of each
BGM per request imply about 15 minutes of playback; allow roughly 25–45 minutes
with notes/replays/breaks. This is a planning estimate, not observed human effort.

Save progress before a break or closing. Changing request saves progress. Labels
are stored at **`outputs/benchmark/labels.json`**, with anonymous clip/query IDs,
relevance, notes, play counts and actual active playback seconds. Restart resumes
saved judgments; Download labels makes a backup. No judgment is preselected.
Pause audio while taking a break. No rank, score, model identity, source filename,
provider or generated description appears in the labeling surface. Do not inspect
`prepared/predictions.json`, `blind-map.json` or source evidence until labeling ends.

## Exact corpus and source evidence

13 assets, **7,085,135 original bytes**; independent SHA-256 and sizes are recorded
in `manifest.json`. Originals are unchanged source attachments. **No source previews
were acquired**, `preview=null` on every record. The player serves these originals,
including range requests; excerpt buttons seek them without creating derivatives.

| Source | Assets | Authors | Coverage selected from source metadata |
|---|---:|---|---|
| OpenGameArt | 9 | Spring Spring / Julie Damsgaard (6), EZduzziteh (1), yd (1), Kistol (1) | menu, footsteps, door, teleport, item, error, two BGM |
| UI SFX, pinned GitHub | 4 | Yuki Capital | arcade select/success/error/level-up |

All **13/13 eligible**, 0 review-required, 0 ineligible at preparation under
`commercial-game/1.0`; reevaluated at launch, playback and saving. Captured asset
pages, audio-specific license and CC0 legal terms are hashed in `evidence/`, with
exact asset byte scope and check date **2026-09-30**. The recorded CC0 grants permit
commercial use, modification and embedding/distribution under the explicit policy;
they do not establish absence of third-party claims or a legal guarantee.
`eligibility-at-preparation.json` is an audit observation; recomputation is authoritative.

The second source is pinned to `romainsimon/uisfx` revision
`9950fe66f993a6660dab9c2651dcbcd899ffd83b`. LICENSE-AUDIO explicitly covers
`packages/uisfx/sounds` and excludes `.generated`. These four published assets are
procedurally generated game/UI sounds, not the Issue #2 synthetic mechanics fixtures.
OpenGameArt provides separate authors and BGM, including 104.577s and 130.234s
original tracks. Published synth/game SFX are included alongside source-labeled
movement/interaction assets; no listening-based classification is asserted here.

Sources: [Various Sound Effects](https://opengameart.org/content/various-sound-effects-0),
[Error](https://opengameart.org/content/error), [Searching](https://opengameart.org/content/searching),
[Etirwer](https://opengameart.org/content/etirwer),
[pinned UI SFX audio grant](https://github.com/romainsimon/uisfx/blob/9950fe66f993a6660dab9c2651dcbcd899ffd83b/LICENSE-AUDIO).
`acquire_selected.py` preserves the fixed individual selection and source URLs.
It performs no crawling, parsing or pack download. Evidence pages are single
reviewed snapshots, not a harvested catalog. With the committed manifest present,
the script verifies bytes/eligibility without network access or refreshed assertions.

## Requests and prepared comparisons

The frozen prompts are in `queries.json`; do not edit them after collecting labels.

| Query | Coverage |
|---|---|
| q01 | UI navigation tick |
| q02 | UI confirm |
| q03 | UI error |
| q04 | Movement / footsteps |
| q05 | Interaction / powered door |
| q06 | Portal / transition |
| q07 | Stage clear / level-up |
| q08 | Electronic ambient BGM |
| q09 | Acoustic guitar BGM |
| q10 | Confusable positive pickup vs warning |
| q11 | Negative wording: confirmation without buzzer/alarm |
| q12 | Long BGM beyond opening ten seconds |

The actual #5 model/index produced **36 segment vectors**, with full rankings and
scores for all 12 prompts in `prepared/predictions.json`. Evaluate K=1,3,5.
Methods: raw semantic full-segment best-match retrieval; native candidate-ID filters
for preregistered measured-duration constraints; native Qdrant first-segment-only
ablation on the same pinned vectors. Constraints are analyst-side and hidden from
reviewers. The duration heuristic can reject relevant sounds (e.g. a >3s error);
the experiment must measure this rather than assuming it improves results.

`prepared/session.json` and `blind-map.json` bind exact manifest/query content to
package **`60ddd8ab1ae0b34911fb9d2838b3b154432826ccca897f03085ab835886a4f06`**.
The audition order is deterministic and independent of model rank. The local HTTP
server has an explicit route allowlist and does not serve analyst files/evidence.

## After human labels exist

```powershell
.venv/Scripts/python.exe -m audio_selector.benchmark_metrics
# Outputs outputs/benchmark/metrics.json; no issue/PR state changes.
```

This refuses incomplete, duplicate, wrong-package and Unsure judgments. Recall@K
uses all corpus positives. AP@K uses scikit-learn AP on retrieved items, scaled by
retrieved positives / all corpus positives, giving truncated AP normalized by R.
mAP averages defined per-query AP; zero-positive queries are reported separately
as undefined, never silently fabricated positives. Reports include per-query values
and sample sizes, not one synthetic accuracy number.

Count reduction compares unique Top-K audition sets to exhaustive corpus review.
Projected time reduction applies actual per-clip human playback logs to those sets;
it is a **counterfactual estimate**, not a measured causal improvement or a substitute
for subjective judgments. Replays are included in the logged time/play counts.
For a later separately conducted timed comparison, enter paired observations for
every query using `effort-template.csv` headers and exhaustive/shortlist methods:

```powershell
.venv/Scripts/python.exe -m audio_selector.benchmark_metrics --effort outputs/benchmark/observed-effort.csv
```

Do not fill that CSV from guesses. The optional report labels these as descriptive
human-recorded observations. Order/memory effects require a controlled future study.

To reproduce model/index preparation before labeling (requires cached/downloaded
pinned HF model): `.venv/Scripts/python.exe -m audio_selector.benchmark`.
This preserves the corpus/query package and never creates labels. Qdrant state is
derived and ignored. Do not regenerate a changed package midway through labeling.

## Risks and exclusions

Small, deliberately selected corpus; no claim of representative production quality.
Procedural UI sounds are one part of the corpus and can cause source/style bias.
Best-of-segments may favor longer files. Nonoverlap segments can miss boundary
events; negation is not enforced by CLAP. Full-corpus human review is necessary
for true Recall. Tastes, fatigue and actual game fit remain entirely unresolved.
CC0 assertions do not guarantee uploader authority or claim-free deployment.

Excluded source candidates (never indexed): Kenney interface ZIP because bounded
individual source files were unavailable without pack acquisition; Freesound
originals requiring authorized login/API access were not acquired; Water Splash and
Sand Footsteps had an additional attribution request that needs a concrete fulfilled
credit plan. No unresolved asset was silently admitted to reach a corpus count.

**Stop here for human audition.** Issue #6 remains open and PR #12 remains Draft.
No human-dependent acceptance criterion, preference weighting or production approval
has been completed.
