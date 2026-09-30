# Issue 4 validation — Windows, 2026-09-30

Start: `50d20a8f2ab272d1f434b708658c3a182143d1e4`.
Branch: `agent/issue-4-manifest-license-gate-v1.0`; Draft PR #10.

Implemented typed authoritative manifest, schema 1.0, explicit commercial-game/1.0
policy, hashed snapshots scoped to exact bytes, independent original/preview blobs,
recursive derivative lineage and freshly computed decisions. Downstream API is
`load`, `evaluate`, `eligible_candidates`; see manifest-contract.md.

Validation executed:

- `python -m unittest discover -s tests -v`: 9 passed.
- `python -m unittest discover -s research/issue-2 -p test_export_evidence.py -v`: 5 passed.
- `python -m audio_selector.manifest tests/fixtures/manifest/manifest.json --require-all-eligible`: exit 0.
- `git diff --check`: passed.

Tests exercise allowed/denied/unknown rights, missing grants, attribution fulfillment,
stale/future/missing/changed/unbound evidence, changed originals, previews, derivative
parents/cycles, malformed schema, duplicate IDs, attempted forged eligibility and CLI
exit 0/2/3. No retrieval dependencies/implementation included.

Remaining limitations: assertions must be faithfully entered/reviewed by an importer
or human. Hashes prove snapshot/byte integrity, not truth of a legal assertion. The
small committed fixture is illustrative nonplayable bytes, not benchmark audio.
No provider-wide permission inference or automatic legal conclusion is made.
