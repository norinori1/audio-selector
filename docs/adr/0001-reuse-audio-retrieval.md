# ADR 0001: reuse semantic retrieval; build the selection policy around it

Date: 2026-09-30. Status: **Accepted for research-to-prototype boundary**; production suitability remains gated on a human listening pilot. Implements the architecture decision required by [Issue #2](https://github.com/norinori1/audio-selector/issues/2). No production engine is introduced by this ADR.

## Context and evidence

The README requires a build-vs-reuse gate before a custom semantic search stack. We need eligible, traceable candidates across sources, ranked for game roles and diverse enough for affordable human audition. A retrieval application's README is insufficient evidence of a working architecture.

[Candidate evaluation](../research/issue-2-prior-art.md) records all required dimensions and primary sources. [Benchmark](../research/issue-2-benchmark.md) records commands, fixtures, Top-3 scores, failures, setup cost and manual ranking inspection. [Upstream snapshot](../research/issue-2-upstreams.json) pins the repositories inspected.

Unmodified SAS model/index/search functions ran on eight original generated WAV files with a real LAION checkpoint, SQLite and real Qdrant local mode. Its underlying cosine retrieval puts the intended sound first for seven basic queries. SAS's application score inversion reverses the returned subset. soundgrep's independently executable embedder/vector components expose a nonsemantic fallback, while its public indexing contracts disagree. These findings justify reusing the dependencies while declining either complete application as-is. The synthetic corpus demonstrates mechanics and defects; it does not establish human relevance, BGM coverage, scale or production asset quality.

## Decision by component

| Component | Classification | Boundary and reason |
|---|---|---|
| Audio-text embedding | **WRAP** | Use LAION-CLAP through Transformers `ClapModel`/`ClapProcessor`. Pin checkpoint revision, preprocessing, crop policy and normalization; expose batch file/text APIs. Fail closed if model unavailable. No model training or fake semantic fallback. Existing CPU execution is sufficient for initial prototype; measure GPU later. |
| Local indexing / vector search | **WRAP** | Use Qdrant client local persistence initially; use its native cosine search and payload filters. Keep authoritative manifest IDs in payload. Local mode is exact and not a server/HNSW scale claim; switch to Qdrant server only on measured need. Do not implement vector search. |
| DSP feature extraction | **REUSE AS-IS** | Use SoundFile/librosa and existing loudness tooling where needed. Duration/sample rate/channel/decode/peak/RMS features are observations, not subjective approval. No FFT/DFT implementation. |
| Quality assessment | **DO NOT USE** | Exclude PAM and general learned quality penalties from initial ranking. Intentional noisy/distorted SFX can be useful; no human game-audio correlation established. A later optional PAM wrapper needs independent validation and weight terms. Retain basic DSP diagnostics. |
| Candidate / provenance manifest | **CUSTOM IMPLEMENTATION REQUIRED** | None of the evaluated applications provides exact bytes, multi-source identity, original/preview distinction, license evidence, lineage and reproducible selection export together. Store hashes and immutable evidence references separately from generated descriptions. |
| License gate | **CUSTOM IMPLEMENTATION REQUIRED** | Apply explicit usage policy to recorded evidence before eligible Top-K. Unknown terms require review; scores cannot override eligibility. Service access terms, code/model licenses and final asset permissions are distinct. This is evidence-backed policy, not an automatic legal conclusion. |
| Game-role ranking | **CUSTOM IMPLEMENTATION REQUIRED** | Compose existing semantic similarity/DSP/verified metadata against project role profiles; expose each score contribution. Role prompts do not prove suitability or reliably implement negation. Keep consumer-specific profiles outside generic source evidence. |
| Diversity reranking | **WRAP** | Use an established MMR or equivalent reranking implementation and documented algorithm; custom work is policy/weights and candidate grouping, not a new similarity engine. Select an appropriately licensed maintained library in the follow-up pilot; this ADR does not claim an implementation was validated here. Include duplicate/hash/pack constraints and eligible-pool overfetching. |
| Audition UI | **FORK / EXTEND** | If the SAS Gradio shell fits, make a bounded MIT fork for an ordered audition queue, provenance/license display, human decisions and export. Validate Windows preview paths and correctness first. Existing player/UI components remain reusable if the shell fails the pilot. No Unity integration. |

## Candidate dispositions

- **LAION-CLAP: WRAP**, preferably Transformers inference rather than the entire research/training package. Code CC0 and selected HF checkpoint Apache-2.0 are different layers.
- **semantic-audio-search: FORK / EXTEND** only for a bounded UI/API prototype; reference implementation for the core dependencies. **DO NOT USE** unchanged, including the inverted hybrid scoring. Fixing a proxy's returned Top-N is insufficient without correct eligible-pool retrieval.
- **soundgrep: DO NOT USE** as the application or fork base for this project now. Optional CLAP configuration, integrated indexing/API behavior and Windows runtime friction need repairs; missing complete root license notice also makes copying premature. Keep source as reference, not vendored code.
- **DCASE 2023/2024: REUSE AS-IS** evaluation conventions and licensed reference utilities when needed; **DO NOT USE** the dataset training pipeline as production tooling. **DCASE 2025: reference only** for multiple-positive evaluation and segmentation; resolve missing code-license grant before reusing code.
- **Microsoft CLAP: DO NOT USE** as default backend. Archived code and MS-PL hosted weights add maintenance/license considerations without demonstrated gain here; retain as a future comparison if human evaluation motivates it.
- **Freesound: WRAP** optional authorized source discovery/API metadata adapter. Hosted search does not index all local sources. Preserve selected original bytes independently from preview streams; respect quotas and access terms. No scraping or bulk-library acquisition.
- **PAM: DO NOT USE** in initial ranking. Optional research follow-up only.
- **AudioCards: WRAP** verified metadata concepts (acoustic attributes, actor/action, context) into project enrichment. Do not assume released descriptions, proprietary audio and trained models share a license. No new captioning model in this gate.

## Intended data flow and contracts

```text
source adapters / manually imported authorized files
  -> manifest (original/preview hashes, source IDs, evidence, lineage)
  -> explicit eligibility decision for intended use
  -> LAION embedding adapter -> Qdrant eligible-pool Top-K
  -> role score composition with visible contributions
  -> established diversity reranker + duplicate/pack policy
  -> ordered audition queue with source/license evidence
  -> human shortlist / final selection / manifest-based export
```

The manifest is authoritative; an index is rebuildable derived state. Store embedding backend/model revision, preprocessing policy, segment offsets and content hash so stale vectors cannot be mixed. Qdrant's cosine direction remains higher-is-more-similar; do not treat it as confidence probability. Apply license filters inside retrieval, not only after taking Top-N. For eligibility changes/deletions, invalidate derived payloads/index records and verify retrieval cannot return blocked candidates.

Positive and negative descriptions may be encoded separately and composed downstream after evaluation. Hard exclusions belong in policy/metadata filters. A prompt containing “without” is insufficient; the benchmark's negative description did not retrieve the intended chime first. Long BGM needs segment coverage rather than SAS's first-ten-seconds-only ingestion. These are adapter/selection choices around existing embeddings and indexes.

## Alternatives rejected

Building CLAP/vector search/DSP from scratch has no supporting evidence: real reusable inference and indexing worked. Full soundgrep adoption adds unrelated music-production dependencies while leaving retrieval integration incomplete. Direct SAS deployment preserves incorrect ranking and lacks the exact-asset/license workflow. Freesound-only retrieval leaves other sources unindexed and depends on hosted metadata/ranks. DCASE production adoption introduces research data/training workflows and licensing questions without asset audition features. Training a game-audio foundation model, custom perceptual metrics and Unity integration remain out of scope.

## Consequences and unresolved gates

The custom scope is narrowed to evidence/eligibility, role/policy composition, diversity constraints, audition state and human evaluation. Existing model/index/DSP/UI primitives do the heavy lifting. This supports the README hypothesis without claiming an off-the-shelf complete workflow exists.

Before production: validate human listening on licensed real SFX/BGM, long-file segments, negative descriptions, latency/memory at useful scale, Windows persistence/UI paths, model/dependency maintenance, distribution notices, and actual API terms. Resolve soundgrep/DCASE2025 licensing before any copying; measure PAM before enabling it. The precise diversity package and UI fork scope are follow-up choices, not completed implementations.

[Revised follow-up backlog](../research/issue-2-prior-art.md#revised-follow-up-work) supersedes engine-building assumptions in epic #1. This branch deliberately contains research scripts/reports only. No PR is merged by this decision.
