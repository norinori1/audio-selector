# Issue 5 validation — Windows, 2026-09-30

Prepared starting SHA: `a542cda2fa9a3bf191cea36f126cc211f0f0edce`.
Branch: `agent/issue-5-laion-qdrant-adapter-v1.0`; Draft PR #11.
Completed #4 (`7566ef242d3ad8a14bc7c77cfea8b0de30e0e4cf`) integrated using an
explicit base-integration commit, preserving prepared history and PR base.

Fresh Python 3.11 Windows environment installed exact dependencies. First model
load in that environment succeeded (existing shared Hugging Face cache reused;
not claimed as a cold network download). Actual CPU CLAP inference and native
Qdrant local persistence were used, without replacement embeddings.

Executed full real-model test suite with `AUDIO_SELECTOR_REAL_MODEL=1`:
12 tests pass, including all 9 manifest tests. Existing research tests: 5 pass.
`git diff --check`: pass. See retrieval-contract.md for reproducible commands and
requirements-retrieval.lock.txt for the complete installed environment.

Integration coverage:

- Real audio/text batch embeddings and unit L2 norm; high beep query ranks beep first.
- Index build: two mechanics-only generated WAVs, four vectors (21-second file has three segments).
- Close parent index; fresh subprocess reloads persisted SQLite/Qdrant, loads cached pinned model,
  runs natural-language Top-2 query; candidate order agrees with first process.
- Reindex same directory; eligible candidate blocked by denied/unknown/missing grant
  disappears before Top-K; removed candidate also disappears.
- Modified bytes excluded immediately; still-eligible metadata update raises StaleIndexError.
- Model revision and preprocessing mismatch reject the persisted index.
- Model unavailable exception propagates without fallback.
- Stereo/downsampled input and zero-padded long-file tail verified.

Observed initial failure: Qdrant 1.12.1 local delete_collection left deleted SQLite
handles open, causing WinError 32 during test cleanup. Upstream source inspected;
adapter rebuild now clears all points through native FilterSelector instead of
deleting the collection. All assertions and cleanup pass after this change. ADR
architecture remains valid.

Limitations: this validates mechanics on generated files, not human relevance.
Real permitted SFX/BGM and subjective judgments belong to Issue 6. Coarse segmentation,
English prompts, negative wording, full-file decode and local overfetch remain risks.
