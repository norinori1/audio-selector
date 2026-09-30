# Issue 8 validation

Windows 11, Python 3.11 venv (`requirements-retrieval.lock.txt`), Google Chrome (installed
build) driven over the DevTools protocol with Node 24's built-in WebSocket client. Corpus: a
scratch copy of the 13-asset benchmark in a directory named `browser corpus ü` (space +
non-ASCII) so missing/changed/blocked cases never touched repository files. Rankings were
produced live by the Issue #7 CLI (`bgm-loop` and `ui-confirm` requests).

## Automated tests

`$env:AUDIO_SELECTOR_REAL_MODEL='1'; .venv/Scripts/python.exe -m unittest discover -s tests`
-> **61 tests OK, 0 skipped** (17 #4-#6, 23 #7, 21 #8); research suite 5 OK. Wheel build
includes `audio_selector/ui/*` and the `audio-audition-queue` entry point. Issue #7 code and
benchmark artifacts are unchanged from `8a1e25d`.

### Export/import hardening (review follow-up)

`TamperWithRecomputedHashTests` edits a field of a valid export, **recomputes a valid
`content_sha256`**, asserts `global_issues == []` (so detection cannot come from the hash) and
requires `verified: false` with the named check plus a refused import that creates no state:

| Case | Tamper (selection only; frozen package untouched) | Detected by |
|---|---|---|
| A | `rank` + 1 | `ranking_identity` |
| B | `pre_diversity_score`; one contribution; reranking reasons | `ranking_score` |
| C | config fingerprint; index state; model revision | `ranking_context` |
| D | top-level decision / note / decided_at vs last event; invalid last event | `decision` |
| E | provenance / eligibility snapshot vs last event (either side) | `decision_snapshot` |

`AtomicImportTests` pre-populates a target state, builds hash-valid exports that are internally
invalid (valid packages followed by an unparseable `decided_at`; a selection whose package was
removed; a duplicated selection identity) and asserts the import raises and `state.json` is
**byte-identical** afterwards; a valid import still merges, keeps existing records, and a
repeated import does not rewrite the file.

Root causes were confirmed by running the same 10 tests against the previous `selection.py`
(`6ed1e02`): 9 failed. The old `verify_export` compared only candidate/representation/hash and
read model/config from the selection's own copy. The old `import_export` persisted each package
via `add_package()` before validating selections, which left an extra package in `state.json`
(partial import), and silently de-duplicated duplicated selections.

The 21 #8 tests (`tests/test_audition_queue.py`) run against a copied corpus in a path with a
space and `ü` and cover: packages bound to their ranking hash (tampered state rejected); no
pre-filled decisions; decisions and history survive store reopen and server restart;
identity must match the package; missing, substituted (another candidate's bytes) and
ineligible assets cannot be selected or played (409) while Reject stays possible; export
contents (hash, provenance/evidence, eligibility, model revision, config version, score
breakdown); no absolute local path or home directory in exports or API responses; immutable
export files; full export -> verify -> import -> re-export roundtrip with identical records;
explicit mismatch reporting for tampering, model contract, config fingerprint, bytes,
eligibility, evidence/provenance and removed candidates; import conflicts never overwrite;
CLI exit codes; HTTP Range on short SFX and mid-file BGM; token/Origin/Host checks; traversal
probes 404; CSP header present.

## Browser validation (Chrome, Windows)

| Check | Result |
|---|---|
| Launch | `serve` printed `http://127.0.0.1:8766/`; page rendered provenance summary, 5-item queue, 8 ranked-but-not-queued, excluded/suppressed lists |
| Layout | Found and fixed horizontal overflow (fieldset `min-content` + nowrap note label); page `scrollWidth == clientWidth` afterwards |
| Decode of exact bytes | All 13 served streams decoded by Chrome's Web Audio; SHA-256 computed in the browser matched each manifest hash |
| Short SFX | `oga-footsteps` (0.73 s) played to `ended`, no media error |
| Long BGM playback/seek | `oga-searching` (104.58 s): `seekable` 0-104.58; Start played; Middle excerpt seeked to 47.29 and advanced to 50.2 in 3 s; End excerpt seeked to 94.58 and advanced to 97.5 in 3 s (final 6/6 runs); direct seeks during playback 3/3; standalone seek-while-playing 9/9; see the unresolved pause observation below |
| Decisions via UI | Shortlist + note, Maybe, Reject saved through radio/Save controls; export button wrote `selection-...json`, "All exported identities verified" |
| Wording | No "best", "production" or "recommend" labels on buttons/headings/badges |
| Restart persistence | Server stopped and restarted **without** `--ranking`; both packages and all three decisions (with timestamps) reloaded from `state.json` |
| Missing file | `oga-etirwer` deleted: card flagged "local file missing", no player, audio 409, Maybe decision still shown, Accept disabled, Reject enabled |
| Changed hash | `oga-door` overwritten with `oga-item` bytes: "expected 7d95b4862040..., found b2790e0e5618...", no player, 409, never substituted |
| Blocked / ineligible | `uisfx-error` rights set to commercial denied: "eligibility now ineligible: commercial: denied", blocked card |
| Ranking config change | Restart with config 1.0.1: banner "current ranking configuration differs ... historical package" |
| Export/import roundtrip | Historical export SHA-256 unchanged after the damage; `verify-export` against damaged corpus + new config exit 3 with per-item mismatches (`bytes`, `eligibility`, `ranking_config`); against intact corpus + original config `verified: true`; `import` into a fresh state: 1 package, 3 records, 0 conflicts |
| Privacy | API/exports contain no absolute paths; loopback-only bind; Host/Origin/token enforced (tests) |

### Observations and limits of this validation

- The Claude-in-Chrome extension tab stayed `document.visibilityState = hidden` (window not
  foreground), and Chrome defers media loading for hidden pages, so element playback was
  validated with a separate **headless** instance of the installed Chrome instead
  (`--autoplay-policy=no-user-gesture-required --mute-audio`). No audible listening test was
  performed by the assistant.
- **Excerpt code review (follow-up).** `render()` pauses players only on startup/package switch;
  the `play` handler pauses only other players; no race found there. One deterministic defect
  was reproduced (2/2): after an excerpt button, a seek from the native scrubber kept the stale
  excerpt stop, so the next `timeupdate` paused at the new position (traced to the excerpt
  handler). Fixed minimally: a seek not started by an excerpt button ends the excerpt window.
  After the fix (headless, 3 runs): scrub after Middle kept playing (80 -> 82.4 s); Start
  advanced; Middle excerpt stopped as designed at about 57.3 s (the only script `pause()`);
  End advanced 94.58 -> 97.5 s. This defect does **not** explain the observation below, where
  no script `pause()` occurred.
- **Headed check not possible:** the Claude-in-Chrome tab again reported `hidden` on
  2026-10-01, so Start/Middle/End were not operated in a headed window.
- **Unresolved:** in 8 of 18 headless runs that used the Start/Middle/End excerpt buttons,
  Chrome fired an unexpected `pause` event 0.1-3 s after an excerpt seek (in every traced run,
  no `pause()` call came from page script, so the pause was browser-initiated). It did not occur in
  the final 6 button-only runs, 3 direct-seek runs on the page's own player, or 9 standalone
  seek-while-playing runs. Switching players to `preload="none"` (so only the auditioned
  player holds a media pipeline) did not by itself eliminate it in the harness. The cause
  (headless media pipeline vs. excerpt seek handling) is not established; a headed manual
  check by the reviewer is required. Pressing play resumes playback; no data is affected.
  Re-running the same harness 6 times after the follow-up showed 0 browser-initiated pauses;
  because the original pauses involved no script call, this is not attributed to the fix and
  the observation remains open until a headed check.
- The server log recorded no errors throughout.
