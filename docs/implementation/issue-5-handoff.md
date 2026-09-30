# Issue #5 Implementation Handoff

Issue: #5 — pinned LAION/Transformers + Qdrant retrieval adapter

## Dependency
This branch is stacked on the #4 branch. Treat the manifest/eligibility contract from #4 as authoritative. Do not duplicate or redesign it unless #4 exposes a concrete blocker; document any required change explicitly.

## Objective
Wrap the reusable retrieval stack selected by ADR 0001:
- LAION CLAP through Hugging Face Transformers;
- Qdrant local persistence for vector search.

## Guardrails
- No custom embedding model or vector search.
- Pin model/checkpoint revision and preprocessing policy.
- No fake/random/nonsemantic fallback.
- Only eligible candidates may enter the index/retrieval pool.
- Preserve candidate manifest IDs and content hashes in derived index metadata.
- Raw cosine is inspectable and never presented as probability/confidence.
- Detect stale vectors across content/model/preprocessing changes.

## Required Windows validation
- first model load;
- index build;
- persisted Qdrant reload after process restart;
- text query -> Top-K;
- reindex;
- eligibility removal/change -> blocked candidate cannot be returned.

## Completion
Update the Draft PR with exact model revision, preprocessing contract, persistence path, tests, and reproduction commands.
Do not merge.