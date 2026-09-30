# Issue #8 Implementation Handoff

Issue: #8 — human audition queue + reproducible selection export

## Dependency

This branch is stacked on Issue #7 / PR #14.

Consume the ranked, inspectable Top-N output produced by #7. Do not duplicate or bypass the #4 manifest, #5 retrieval adapter, or #7 role/diversity layer.

## Objective

Provide the final human-in-the-loop audition workflow:

```text
ranked Top-N
  -> listen
  -> accept / shortlist / maybe / reject
  -> optional note
  -> persist decisions
  -> reproducible selection export
```

This is a selection UI/workflow, not an automatic decision maker.

## Reuse-first requirement

Before choosing the UI architecture, explicitly evaluate the existing semantic-audio-search Gradio shell/components referenced by ADR 0001.

Record:
- what can be reused safely;
- what cannot be reused because of its retrieval path or assumptions;
- whether a bounded fork/port is smaller than a new UI.

Do not route searches through SAS's incorrect/incompatible ranking implementation. #7 output remains authoritative for ordering.

## Required UI information

For every result expose:

- rank;
- playable preview/original as permitted;
- stable candidate ID;
- source/provider;
- title/author where recorded;
- license summary;
- evidence/provenance status;
- eligibility status;
- exact original-vs-preview identity;
- byte hash;
- duration/basic metadata;
- semantic score;
- role-policy contributions;
- diversity/rerank contribution/reason;
- ranking/config version.

Human actions:
- accept/select;
- shortlist;
- maybe;
- reject;
- optional note.

Do not pre-fill subjective judgments.

## Persistence

Human decision state must survive restart.

State must bind to exact candidate identity and ranking package/config, not only display title or filename.

Handle:
- missing local asset after restart;
- changed hash;
- candidate becoming ineligible;
- ranking package/version changes.

Never silently substitute a different file.

## Reproducible selection export

Export enough immutable/reproducible information to reconstruct what was selected:

- candidate ID;
- original/preview representation selected;
- exact SHA-256;
- source/provenance references;
- license/evidence IDs or snapshot identities;
- eligibility policy/version;
- model/checkpoint revision;
- index/preprocessing contract;
- #7 ranking config/version;
- score breakdown;
- human decision/note;
- decision timestamp;
- export schema version.

The export must fail or prominently flag if the current bytes/evidence no longer match the selected identity.

## Import/roundtrip

Support importing a previous selection export or persisted session and verify:
- exact identity match;
- eligibility state;
- hash match;
- config/version metadata;
- human decision preservation.

Do not mutate historical decisions silently when current ranking changes.

## Windows validation

Validate at minimum:
- local browser launch;
- playback of short SFX;
- playback/seek of long BGM;
- Windows path handling;
- state save + process restart;
- missing-file behavior;
- ineligible/blocked candidate behavior;
- exact-hash mismatch behavior;
- export/import roundtrip;
- no access to unrelated private/local paths.

## UX constraint

The tool may show ranking rationale, but the human remains the final decision maker.

Do not label a result "best", "production-ready", or automatically accepted solely from model score.

## Completion

Update the Draft PR with:
- SAS UI reuse evaluation;
- chosen UI boundary;
- launch command;
- persistence schema;
- export schema;
- screenshots/textual validation evidence as appropriate;
- Windows/browser tests;
- export/import roundtrip tests;
- known limitations.

Do not merge.