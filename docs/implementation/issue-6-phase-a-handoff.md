# Issue #6 Phase A Handoff — Human Benchmark Preparation

Issue: #6 — human preference benchmark for real SFX and BGM

## Dependency
This branch is stacked on #5, which is stacked on #4.

Use the manifest/license gate from #4 and the retrieval adapter from #5. Do not duplicate either subsystem.

## Objective for this PR
Prepare the complete benchmark package **up to, but not including, human relevance judgments**.

This is intentionally Phase A only.

## Required preparation
- Build a small real-world SFX/BGM benchmark corpus using only assets whose exact evidence/eligibility is resolved by #4.
- Prefer multiple sources where safely and explicitly permitted; do not collapse the corpus to one provider merely for convenience.
- Do not scrape or bulk-download.
- Preserve original/preview identity and exact hashes.
- Define blinded benchmark queries/roles covering at least:
  - UI navigation / confirm / error;
  - movement / interaction;
  - portal / transition;
  - stage clear;
  - at least one BGM query.
- Include confusable classes, negative wording, and long-BGM/segment cases.
- Run the #5 retrieval path and materialize Top-K candidate sets without revealing rankings in the human labeling surface.
- Prepare a human audition/labeling artifact or local UI that supports multiple relevant answers and records judgments reproducibly.
- Prepare evaluation scripts for Recall@K, mAP@K (or equivalent multiple-positive metric), and audition-count/time reduction.
- Document exact instructions for the human reviewer.

## HUMAN REVIEW STOP GATE

Stop once the repository contains a reproducible package that lets the human reviewer listen and label candidates.

Do NOT:
- invent human labels;
- infer "pleasant", "fatiguing", "LayerTrace-like", or production suitability on the human's behalf;
- complete #6 acceptance criteria that require human listening;
- tune #7 weights using synthetic or fabricated preferences;
- mark #6 complete;
- merge this Draft PR.

At the stop gate, update the PR with:
1. corpus summary and source breakdown;
2. exact license/evidence status;
3. benchmark queries;
4. how to launch the audition/labeling flow;
5. estimated number of clips/judgments the human must make;
6. where human labels will be stored;
7. commands that will compute metrics after labels are supplied.

The next action must be explicitly "human audition required".