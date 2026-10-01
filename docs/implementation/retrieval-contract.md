# Retrieval contract 1.0

ADR 0001 is retained. Transformers `ClapModel`/`ClapProcessor` load
`laion/clap-htsat-unfused` at immutable revision
`8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`. No checkpoint or fake-vector fallback.
Audio/text/files support batching. CPU inference uses four threads and eval mode.

Original audio only: SoundFile float32 decode, arithmetic channel mean, librosa
soxr_hq resample to 48 kHz, contiguous nonoverlapping 10-second segments over the
whole file, zero-padding final/short segments to 480000 samples. No random crop,
loudness normalization or first-ten-seconds-only ingestion. The pinned processor
extracts CLAP features. Text uses its pinned tokenizer, padding and truncation to
77 tokens. Audio and text vectors are finite, nonzero and L2-normalized.

Segment counts and unpadded start/end offsets come from the actual array after
decode, channel mean and resampling, never `sf.info()` frame estimates. Both
`segment_specs()` and `audio_segments()` use this path; index embedding pairs
specs and arrays from a single decode. The slice is padded by
`480000 - len(segment)`, so every model input is exactly 480000 samples even
when compressed-audio metadata overestimates or underestimates its decoded length.
Exact multiples produce no additional empty segment. Padding is excluded from
`segment_end`; point UUIDs retain the candidate ID, original SHA-256 and start
sample identity. CLAP's fixed-length validation remains mandatory.

This fixes the existing whole-file/zero-padding contract; its identifier remains
v1. A failed prior build has no completion marker. An old completed index with
estimated offsets or omitted segments fails the existing expected-payload/missing
vector check and requires a rebuild. Already correct segments keep their IDs and
contract. Validation on reload/query now decodes/resamples eligible originals to
recompute actual offsets; this costs more than the previous header-only scan,
without introducing a stale length cache.

Qdrant local persistent directory defaults to `qdrant_storage/default`. Native
512-dimensional cosine search: higher means more similar, never a probability.
Each derived point has manifest ID, original content hash, segment offsets,
model/revision/preprocessing contract, policy version and candidate/evidence/parent
fingerprint. Point UUIDs are deterministic. The manifest remains authoritative.

Before every query, recompute eligibility using intact source evidence and audio.
Compare payloads to expected current records. Removed/blocked/stale points are
purged; missing vectors for eligible records raise StaleIndexError requiring rebuild.
Query uses Qdrant HasId + eligibility/intended-use filters inside native search.
Optional candidate-ID metadata constraints further restrict this pool. Unique
candidate results expose the highest-scoring segment and raw cosine; Qdrant does
all similarity calculation. This small-corpus adapter overfetches all valid segments
to obtain distinct Top-K; it is not a server scaling claim.

A successful-build marker is written atomically only after byte/evidence recheck.
Interrupted/failed rebuilds cannot be queried. Rebuild clears points using Qdrant's
native FilterSelector; it retains the collection because observed 1.12.1 local
delete_collection fails to close deleted SQLite handles on Windows. An incompatible
collection dimension/distance requires a fresh directory. One process owns a local
index at a time; always close before another process opens it. Keep indexes ignored.

```powershell
uv venv --python 3.11 .venv
uv pip sync --python .venv/Scripts/python.exe requirements-retrieval.lock.txt
uv pip install --python .venv/Scripts/python.exe -e . --no-deps
$env:AUDIO_SELECTOR_REAL_MODEL = '1'
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe -m audio_selector.retrieval build path/to/manifest.json
# Exit the process, then open the persisted index in a separate invocation:
.venv/Scripts/python.exe -m audio_selector.retrieval query path/to/manifest.json --text 'a bright confirmation chime' --k 5 --offline
.venv/Scripts/python.exe -m audio_selector.retrieval inspect path/to/manifest.json
# Reindex with the same build command after changes.
```

Use `--policy path/to/policy.json` consistently for attribution/usage obligations.
`--offline` requires the first successful pinned model download in the HF cache.
Source references: [Transformers CLAP](https://huggingface.co/docs/transformers/v4.44.2/model_doc/clap),
[pinned checkpoint](https://huggingface.co/laion/clap-htsat-unfused/tree/8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a),
[Qdrant filtering](https://qdrant.tech/documentation/concepts/filtering/).

Limitations: full-file decoding, full local metadata scan/overfetch, coarse 10-second
segments, English CLAP/truncated text and model bias need human validation. Negative
wording has no hard exclusion semantics. Required hard exclusions belong in policy
or candidate metadata constraints. Dependencies/model maintenance need future review.
