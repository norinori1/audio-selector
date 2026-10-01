# Issue #19 validation

Starting SHA (main): `61fa45ca67ab7d6d9e287a48ca16fb570139cef2`.
Branch: `fix/issue-19-mp3-tail-segment-padding-v1.0`.
Environment: Windows build 26200, Python 3.11.0, the unchanged
`requirements-retrieval.lock.txt`; `uv pip check` passes. SoundFile 0.12.1 uses
libsndfile 1.2.0. CLAP is the real pinned checkpoint from retrieval contract 1.0,
loaded from the local cache, with Qdrant 1.12.1 local persistence.

## Reproduction and implementation

The exact original was downloaded from the MP3 link on the
[official Diaphanous page](https://www.silvermansound.com/free-music/diaphanous).
It is 11,383,035 bytes with SHA-256
`31f8de24525d6a250dba62f15717e2ad7fd9238c32e402cc2177624dfa3ebf89`.
No conversion or preview substitution was used. Audio, source snapshot,
validation-only manifest/policy, logs and persistent index are under ignored
`artifacts/issue-19/`; none are committed. The manifest records the captured
source assertions and attribution for isolated technical validation. It does not
change production candidates, license decisions or audition decisions.

At the starting SHA, `segment_specs()` estimated 13,658,308 target samples from
header frames. `audio_segments()` sliced the actual array but padded by the
estimated `end - start`. The final actual slice was 214,727 samples, yet padding
was only 261,692 samples, producing 476,419. Real `ClapEmbedder.embed_audio()`
raised `ValueError: preprocessed audio must contain exactly 480000 samples`.
This reproduces the issue's observation; no universal MP3 decoder cause is claimed.

The shared decode/channel-mean/resample helper now provides the actual array.
Both public segmentation functions derive boundaries from its length. Index
embedding obtains boundaries and padded arrays from one decode. Every slice has
at most 480000 samples and receives exactly `480000 - len(segment)` zeros.
`range(0, actual_length, 480000)` excludes an extra empty segment at exact
multiples. Payload ends exclude padding; deterministic UUID inputs are unchanged.
CLAP's exact-length validation, byte/evidence recheck and atomic successful-build
marker remain intact. Wrong old estimated payloads require rebuilding through the
existing missing/stale check. The existing preprocessing contract identifier is
retained because this implements its whole-file and fixed-length requirements.

## Exact original results

| Observation | Starting SHA | Fixed implementation |
| --- | ---: | ---: |
| Metadata frames | 12,548,570 | 12,548,570 |
| Decoded frames at 44,100 Hz | 12,545,280 | 12,545,280 |
| Actual resampled samples | 13,654,727 | 13,654,727 |
| Segments | 29 | 29 |
| Final unpadded start | 13,440,000 | 13,440,000 |
| Final unpadded end | 13,658,308 (estimate) | 13,654,727 (actual) |
| Final model input samples | 476,419 | 480,000 |
| Final zero padding | 261,692 | 265,273 |

`LocalIndex.build()` succeeds for the isolated original: one candidate, 29 finite
512-dimensional real vectors, and the successful-build marker. Stored payloads
equal expected candidate/content/offset/contract records. After close, an offline
CLI query in a separate Python process succeeds. Reopening reports 29 valid,
zero stale and zero missing points. Native rebuild succeeds with the same IDs,
payloads and vectors, and query succeeds again. The query is a technical smoke,
not a ranking or audition decision.

Stored vectors are checked with zero relative tolerance and one float32 epsilon
on reload: Qdrant 1.12.1 normalizes into float32 memory on insertion while reloading
persisted input vectors into float64. IDs and payloads are compared exactly.

The optional, network-free runner requires a local exact-original manifest,
intact evidence, explicit policy and cached model; it does not fabricate rights:

```powershell
.venv/Scripts/python.exe scripts/validate_issue19.py artifacts/issue-19/manifest.json --policy artifacts/issue-19/policy.json --index artifacts/issue-19/index --report artifacts/issue-19/exact-original-validation.json
```

Use a dedicated validation index: the build/rebuild replaces its derived points.
The runner records the current git SHA and working diff in the report.
Music: Diaphanous by Shane Ivers - https://www.silvermansound.com

## Regression and existing tests

Seven deterministic preprocessing tests add metadata/decode mismatch with actual
44.1-to-48 kHz resampling, over/underestimates across segment boundaries, normal
tail, exact multiples, short audio, empty decode and preserved CLAP rejection of
invalid lengths. The mismatch tests fail on the original implementation. Fixtures
are small generated local WAVs; unit tests need no external audio download.

One real-model integration regression adds build/reload/query/rebuild, exact
offset/UUID/payload checks, vector persistence, rejection of an old estimated tail
payload, and failure after eight real vectors have been persisted. That failed
rebuild has no marker and cannot query, including after restart; a full subsequent
rebuild recovers. No replacement semantic embeddings are used.

- Starting SHA: Fast CI equivalent, 61 ordinary tests (two expected model skips)
  plus five research tests pass locally.
- Fixed: `python scripts/ci_checks.py fast`, 69 ordinary tests (three explicitly
  audited model skips) plus five research tests pass.
- Fixed: `AUDIO_SELECTOR_REAL_MODEL=1 python scripts/ci_checks.py heavy`, all 69
  ordinary tests plus five research tests pass, with zero skips. This includes
  manifest/audition, ranking, retrieval/preprocessing, frozen benchmark reproduction
  and research tests; both committed schema/CLI comparisons pass.
- `git diff --check` passes. Dependency check and manifest/ranking validation CLIs
  also pass. Tracked benchmark evidence is unchanged.

Main's existing [Fast CI run 36798175538](https://github.com/norinori1/audio-selector/actions/runs/36798175538)
fails `test_committed_metrics_and_rankings_reproduce_without_model` on floating-point
JSON reproduction. That failure occurs at the unchanged starting SHA on Actions;
both local baseline and fixed runs pass it. No benchmark, ranking arithmetic,
tolerance or unrelated CI failure is modified by this issue.

## Remaining limits

Expected-record validation now fully decodes/resamples eligible originals on
build/reload/query, increasing CPU and I/O versus header-only scanning. The adapter
already decodes entire files; large-corpus performance remains unmeasured. The
exact original validation covers one isolated candidate, rather than repeating
LayerTrace's seven-candidate audition preparation. External MP3 retrieval and
model availability are optional validation prerequisites, not unit-test gates.
