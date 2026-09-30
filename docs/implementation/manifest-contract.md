# Manifest and eligibility contract 1.0

`audio_selector.manifest.Manifest` is authoritative JSON. `Candidate.id` is an
assigned stable identifier, independent of mutable provider URLs and derived
index IDs. Exact original and optional preview `Blob`s have independent SHA-256,
size, filename, media type and path. Paths resolve relative to the manifest.
Multiple providers and multiple records sharing bytes are supported.

Evidence is a captured, hashed snapshot, a source URL, check date, human-recorded
interpretation notes and explicit exact-byte scope. Record source metadata and
license evidence separately through references. The importer/reviewer must check
that the source grant really identifies those assets: recording an assertion is
not legal verification. Source reputation, model/code licenses, generated captions
and similarity scores confer no asset rights.

Rights assertions use allowed/denied/unknown; absent values mean unknown. The
commercial-game/1.0 policy requires explicit commercial and game-embedding grants,
resolved attribution, redistribution restrictions and claim notes, fresh evidence
(365 days), and matching evidence/audio bytes. Attribution-required assets need
an explicit fulfilled-attribution ID in the usage policy. Standalone redistribution
and modification can additionally be required. Preview use is blocked by default;
enabling it still requires evidence scoped to those preview bytes. A derivative
needs a parent, transformation notes, its own scoped grant, and recursively eligible
parents with explicit modification permission. Cycles/dangling parents are invalid.

`evaluate(manifest, id, manifest_directory, policy)` returns a separate timestamped
Decision with status, reasons, intended use, policy version and selected hash.
`eligible_candidates` is the downstream gate. Always recompute; never trust a
persisted decision. Missing bytes/evidence, stale/future evidence or unknown rights
yield review-required. Explicit prohibitions yield ineligible. Neither enters the
eligible pool. Changing policy/manifest/evidence must invalidate derived state.

Schema and policy versions are independent. Unknown schema/policy versions fail
validation; changes require an explicit migration/version increment. No automatic
upgrade or legal inference is provided.

```powershell
python -m pip install -e .
python -m audio_selector.manifest --schema
python -m audio_selector.manifest --hash path/to/original.wav
python -m audio_selector.manifest path/to/manifest.json --require-all-eligible
python -m unittest discover -s tests -v
```

CLI exits: 0 structurally valid, intact references; 2 invalid schema or missing/
changed bytes; 3 valid but not all eligible when `--require-all-eligible` is set.
Noneligible entries are otherwise valid manifest state. An empty manifest is valid.
Test fixture construction in `tests/test_manifest.py` illustrates JSON fields but
does not represent acquired/licensed audio. Export schema via `--schema`.
