# Issue 6 Phase A validation — Windows, 2026-09-30

This is the historical preparation record. After its human-audition stop, the user
provided actual labels and explicitly requested the
[human pilot report](../../benchmark/evaluation/human-pilot-v1.md). Statements below
about absent labels and unresolved relevance describe the Phase A stop, not the
subsequent report. Actual effort benefit and production suitability remain unresolved.

Prepared start: `6e5bb8dd873a529e7240d8816ac09f7cb1bfca86`.
Branch: `agent/issue-6-human-benchmark-prep-v1.0`; Draft PR #12.
Completed #5 `bf526cb45c72908f537482ac6406d9f3af2f267e` integrated with the
prepared branch history preserved. #4/#5 origin branches remain independent Draft PRs.

13 unchanged individual originals from two sources, 7,085,135 bytes. OpenGameArt
9 / UI SFX 4, five authors/creators. Six evidence records: four exact asset pages,
pinned audio-specific grant, CC0 legal terms. All byte scopes/snapshots/originals
verified by manifest gate; 13 eligible, 0 review-required, 0 ineligible. Source
preview state explicitly absent. See benchmark/README.md for source URLs and risks.
Git attributes disable text conversion on evidence/media to preserve exact hashes.

Real pinned #5 pipeline: 36 vectors, 12 prompts, three methods, full candidate
rankings with raw cosine/segment offsets. Package fingerprint:
`60ddd8ab1ae0b34911fb9d2838b3b154432826ccca897f03085ab835886a4f06`.
No new similarity/model/database architecture. The first-segment ablation uses native
Qdrant filtering on the same eligible derived points; duration filtering uses #5 API.

Validation executed:

- Full suite with AUDIO_SELECTOR_REAL_MODEL=1: **17 passed**, no skips. Includes all #4/#5 tests.
- Existing Issue 2 research tests: **5 passed**.
- Corpus validator `--require-all-eligible`: exit 0, 13 eligible.
- Acquisition script with existing manifest: verifies all 13 without network requests.
- Benchmark preparation: actual model inference, persistent index and three candidate sets generated.
- Blinding tests verify no score/filename/source/candidate IDs in public session data,
  independent clip ordering, exact pool coverage and blocked private-file HTTP routes.
- HTTP original range access and protected save endpoint tested; launch creates no labels.
- Empty future labels cause HUMAN AUDITION REQUIRED error, not zero-valued results.
- Abstract metric arithmetic checked against known multiple-positive AP/Recall values;
  these unit tests are not human labels and produce no benchmark results.
- Browser automation: all 13 originals decoded with finite duration; visible source
  IDs/cosine absent; empty save roundtrip recorded zero judgments to a separate ignored
  smoke path. Production `outputs/benchmark/labels.json` remains absent.
- Muted browser playback of a middle BGM excerpt advanced beyond 10 seconds and
  enabled the judgment control; no relevance value was entered. This checks player
  mechanics only, and makes no claim to hearing or judging the track.
- `git diff --check`: passed; captured source whitespace is exempt via attributes
  so original evidence pages remain byte-for-byte unchanged.

First preparation attempt used Qdrant MatchValue for a floating segment offset;
Qdrant rejected it. Changed benchmark ablation to native numeric Range(gte=0,lte=0),
then reran successful preparation. No upstream architectural assumption was invalidated.

Hard stop: **HUMAN AUDITION REQUIRED**. Human must label 156 pairs (multiple relevant
clips allowed), inspect long-track start/middle/end, and record qualitative fit/fatigue
notes. Relevance, Recall/mAP results, actual effort benefit and production suitability
remain unresolved. PR #12 stays Draft; Issue #6 stays open. No labels fabricated.
