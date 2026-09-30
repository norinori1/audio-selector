# Issue #4 Implementation Handoff

Issue: #4 — exact candidate manifest + evidence-backed license gate

## Objective
Implement the authoritative candidate/provenance manifest and fail-closed eligibility policy selected by ADR 0001.

## Guardrails
- The manifest is authoritative; indexes/embeddings are derived state.
- Keep license evidence separate from eligibility decisions.
- Unknown or unresolved evidence must never become eligible by default.
- Distinguish original bytes, previews, and derivatives with SHA-256 identity.
- Do not add CLAP, Qdrant, semantic ranking, UI, scraping, or automatic legal conclusions.
- Prefer typed Python models/schema + a validation CLI + focused tests.

## Required validation
Cover at minimum:
- permissive evidence -> eligible when policy allows;
- restrictive evidence -> ineligible;
- unknown/missing evidence -> fail closed;
- stale/missing evidence handling;
- original vs preview identity;
- derivative lineage;
- invalid manifests -> non-zero CLI exit.

## Completion
Update the Draft PR with architecture, tests, example manifest, and exact validation commands.
Do not merge.