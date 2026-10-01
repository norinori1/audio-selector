# audio-selector

Game-audio asset selection tooling for narrowing large, multi-source audio candidate sets into human-auditionable Top-N recommendations.

See [CI validation](docs/ci.md) for the Windows/Python 3.11 PR regression gate,
expected real-model skips, and the separate manual CLAP/Qdrant smoke workflow.

## Status

**Evidence-backed retrieval prototype; real-audio human pilot prepared in a Draft stack.**

ADR 0001 selects LAION CLAP/Transformers and Qdrant reuse. The authoritative
manifest and fail-closed gate are documented in [manifest contract](docs/implementation/manifest-contract.md),
and the pinned adapter in [retrieval contract](docs/implementation/retrieval-contract.md).
The [human audition package](benchmark/README.md) now includes a
[first human relevance pilot](benchmark/evaluation/human-pilot-v1.md) based on 156
user-supplied judgments. A versioned [role ranking + MMR diversity layer](docs/implementation/ranking-contract.md)
has [preregistered in-sample results](benchmark/evaluation/role-results-v1.md): small role
gains at K=3, and a Recall@5 regression from the v1 diversity caps. A loopback-only
[audition queue](docs/implementation/audition-contract.md) plays the ranked Top-N as
verified exact bytes, records your accept/shortlist/maybe/reject decisions, and writes
reproducible selection exports (`python -m audio_selector.audition_queue serve`). Actual audition-time
benefit and production suitability remain unresolved. Start further local review with
`.venv/Scripts/python.exe -m audio_selector.audition` and open the printed URL.

This repository must not begin by reimplementing an audio retrieval engine.

The first gate is to evaluate existing research and OSS, then decide what should be:

- reused as-is;
- wrapped;
- forked / extended;
- implemented specifically for the game-audio workflow.

## Problem

Game projects may draw candidate BGM / SFX from multiple sources with different licenses and metadata.

The intended workflow is:

```text
Multiple audio sources
        ↓
Candidate + provenance manifest
        ↓
License / usage gate
        ↓
Existing semantic audio retrieval
        ↓
Game-role ranking
        ↓
Diversity reranking
        ↓
Top-N audition queue
        ↓
Human listening / final selection
```

The tool should reduce human audition cost. It must not replace the final human listening decision.

## Initial prior art

The first research pass should evaluate at least:

- semantic-audio-search
- soundgrep
- DCASE language-based audio retrieval baselines
- LAION-CLAP
- Microsoft CLAP
- Freesound API / similarity search
- PAM or comparable no-reference audio-quality metrics
- AudioCards / structured sound-design metadata approaches

The project should prefer existing implementations over recreating CLAP, vector search, DSP primitives, or standard retrieval metrics.

## Likely custom layer

The working hypothesis is that custom work may still be useful around:

- multi-source candidate manifests;
- exact-asset provenance and license gating;
- game-specific audio-role profiles;
- positive / negative semantic prompts;
- diversity reranking for audition sets;
- human audition workflow;
- evaluation against human preferences.

This is a hypothesis, not a committed architecture. The prior-art evaluation decides the boundary.

## Non-goals for the research gate

- custom audio foundation model training;
- custom FFT / DFT implementation;
- Unity runtime audio integration;
- automatic legal judgment without source evidence;
- scraping sites where automation is prohibited;
- automatically declaring an audio asset production-ready without human audition.

## Relationship to LAYERTRACE

This repository is intentionally independent from LAYERTRACE.

LAYERTRACE is the first intended consumer and already has audio-source research in:

- `norinori1/LayerTrace#444`
- `docs/research/audio-source-exploration-v1.md`

Game-specific role profiles and selected assets may live in the consuming game repository. Generic retrieval / selection tooling should remain here.

## Development gate

**Do not implement a new semantic search engine until the build-vs-reuse issue is complete and an ADR records the decision.**
