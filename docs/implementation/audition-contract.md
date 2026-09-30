# Audition queue and selection export contract 1.0 (Issue #8)

The human audition step after [role ranking](ranking-contract.md). It never ranks, never
decides, and never approves an asset. Reuse decision: [SAS UI evaluation](issue-8-sas-ui-evaluation.md).

## Architecture

```text
Issue #7 CLI:  audio_selector.ranking query ... --out rank.json      (authoritative ordering)
                           |
audio_selector.audition_queue serve --ranking rank.json
   Store (selection.py) -- state.json: verbatim ranking packages + append-only human events
   verify() on every view/audio/decision/export: manifest identity, local bytes SHA-256,
            path inside manifest root, manifest.evaluate eligibility (current)
   HTTP (127.0.0.1 only): /, /queue.js, /queue.css, GET /api/state,
            GET /api/audio/<package>/<candidate> (verified exact bytes, Range),
            POST /api/decision, POST /api/export (token + Origin + Host checked)
   UI (ui/queue.*): rank order, provenance, scores, player, decisions, export
                           |
exports/selection-<utc>-<hash12>.json   (immutable)  -> verify-export / import
```

`selection.py` has no HTTP; `audition_queue.py` has no ranking or eligibility logic of its own.

## Launch (Windows PowerShell, repository root)

```powershell
.venv/Scripts/python.exe -m audio_selector.retrieval build benchmark/manifest.json --index qdrant_storage/bench --offline
.venv/Scripts/python.exe -m audio_selector.ranking query benchmark/manifest.json --index qdrant_storage/bench --role bgm-loop --text "dark electronic ambient exploration music" --offline --out outputs/audition/rank-bgm.json
.venv/Scripts/python.exe -m audio_selector.audition_queue serve --manifest benchmark/manifest.json --ranking outputs/audition/rank-bgm.json --config benchmark/roles/ranking-v1.json
# open http://127.0.0.1:8766/ ; state: outputs/audition/state.json ; exports: outputs/audition/exports/
.venv/Scripts/python.exe -m audio_selector.audition_queue export --manifest benchmark/manifest.json --require-verified
.venv/Scripts/python.exe -m audio_selector.audition_queue verify-export outputs/audition/exports/<file>.json --manifest benchmark/manifest.json --config benchmark/roles/ranking-v1.json
.venv/Scripts/python.exe -m audio_selector.audition_queue import outputs/audition/exports/<file>.json --manifest benchmark/manifest.json --state other/state.json
```

Later launches may omit `--ranking`; packages persist in the state file. Exit codes: 2 invalid
input, 3 verification failed (`--require-verified` export, `verify-export`, `import`).

## Persistence schema `audition-state/1.0`

```text
packages[]: package_id  = SHA-256 of canonical JSON of the ranking (re-checked on every load)
            added_at
            ranking     = verbatim role-ranking-result/1.0 (query, role, config id/version/fingerprint,
                          retrieval_contract, index_state, eligibility policy version, entries, reasons)
records[]:  package_id, candidate_id, representation (original|preview), sha256   <- exact identity
            events[] (append-only): decision accept|shortlist|maybe|reject|null (null = cleared),
                     note (<= 4000 chars), decided_at (UTC),
                     verification (identity/file/eligibility observed at decision),
                     provenance (manifest candidate record + referenced evidence records + manifest hash)
```

- Decisions bind to (package, candidate, representation, sha256), never filename/title. A record
  whose identity is not in its package is rejected on load.
- Written with temp file + atomic replace; one server process per state file.
- New rankings (config/model/index change) become new packages; old decisions stay with their
  package and are never re-applied or pre-filled elsewhere. No decision is pre-populated.

## Current-state handling

| Situation | Detection | Behaviour |
|---|---|---|
| Local file missing | `verify.file = missing` | Card flagged, no player, `/api/audio` 409; decision history kept; only Reject allowed |
| Bytes changed / substituted | recomputed SHA-256 differs | `hash-changed`, expected vs found hash shown; never served, never substituted |
| Manifest now records other bytes / candidate removed | `identity` state | Flagged; recorded provenance at decision is displayed instead |
| Became ineligible / review-required | `manifest.evaluate` now | Flagged with reasons; not served; accept/shortlist/maybe refused (409) |
| Ranking config differs | `--config` fingerprint vs package | Banner: historical package |
| Model/preprocessing contract differs | package contract vs pinned `CONTRACT` | Banner: historical package |

## Export schema `audition-selection-export/1.0`

Top level: `exported_at`, `tool`, `manifest_at_export` (schema, canonical SHA-256),
`eligibility_policy` (full policy record incl. version), `retrieval_contract_at_export`,
`packages` (verbatim ranking packages used), `selections`, `integrity`
(`all_verified`, `selected_verified`, `flagged[]` with issues), `content_sha256`
(canonical SHA-256 of everything else; tamper evidence).

Each selection: `candidate_id`, `representation`, `sha256`, `package_id`, `rank`, `decision`,
`note`, `decided_at`, `decision_history`, `provenance_at_decision` (manifest record: provider,
source asset ID/URL, author, acquisition, lineage, original/preview blobs, rights; evidence IDs,
URLs, dates and snapshot hashes), `eligibility_at_decision`, `ranking_context` (request, role,
config id/version/fingerprint, CLAP model/revision/preprocessing contract, index state,
eligibility policy version), `score` (pre-diversity score/rank, named contributions, raw
signals, reranking decision/reasons/MMR trace), `verification_at_export`.

Exports are written with exclusive create and never modified; later exports are new files, so
earlier ones remain historical records when ranking, eligibility or files change. Paths inside an
export are manifest-relative; no absolute local path is written.

## Import / verification report `audition-import-report/1.0`

`verify-export` compares an export with the current state and reports per selection:
`ranking_identity`, `identity`, `bytes`, `provenance` (manifest record and evidence records equal
those at decision), `eligibility` (eligible then and now, same policy version), `model_contract`,
`ranking_config` (when `--config` given), `decision` (last event equals exported decision), plus
global issues (content hash, invalid package, policy change). Every failing check is listed in
`mismatches`. `import` refuses modified exports, restores packages and decision histories
exactly, reports identical records as unchanged, and never overwrites a different existing
history (reported as a conflict).

## Local/privacy boundary

Binds 127.0.0.1 only; rejects foreign `Host` headers (DNS rebinding) and foreign `Origin`s;
writes need the per-process token. No request names a path: audio is addressed by
(package, candidate) and resolved through the manifest, and manifest paths resolving outside
the manifest directory are refused. Only three static UI files are served. API responses and
exports contain no absolute local paths. Strict CSP (`default-src 'none'`), `nosniff`,
`no-referrer`, `no-store`; all data is rendered with `textContent`.

## Known limitations

Single-user, single-process state file; no concurrent multi-process writers. Every state view
re-hashes candidate files and evidence (fine for small queues). Preview representations are
supported by the schema but the current ranking layer produces originals only. See
[validation](issue-8-validation.md) for the headless-Chrome playback observation.
