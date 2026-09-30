# Issue 8: semantic-audio-search UI reuse evaluation

Evaluated 2026-10-01, before choosing the audition UI architecture, as required by
ADR 0001 ("Audition UI: FORK / EXTEND if the SAS Gradio shell fits") and Issue #8.

Source inspected: [TaaroBravo/semantic-audio-search](https://github.com/TaaroBravo/semantic-audio-search)
at the commit pinned by Issue #2, `8e7e525b271cce19f19ac25e5340c576107f9d04` (MIT, (c) 2025 Taaro Bravo).
The UI is `ui/app.py` (174 lines), `ui/requirements.txt` (`gradio<4`, `requests`, `pandas`)
and `ui/Dockerfile`. The retrieval/API side is `api/main.py` (836 lines).

## Component inventory

| SAS component | What it does | Verdict |
|---|---|---|
| `gr.Blocks` layout: results `Dataframe` + pick `Dropdown` + HTML `<audio>` player | Search-result table, one selected preview | **Concept reusable** (ordered table + per-result player + source link). About 30 lines; no code copied. |
| `api_search` | Calls SAS `/search` | **Incompatible.** That endpoint is SAS's inverted hybrid ranking (ADR 0001). Issue #7 output must be the only ordering. |
| `api_upload`, `api_update`, `api_delete`, `api_rescan`, "Manage Library" tab | Mutate the SAS library, tags and index | **Incompatible.** The manifest is authoritative; audition must not edit assets, tags or indexes. |
| `_player_html` | Builds `<audio src>` by string interpolation, escaping only `"` | **Not reusable as is.** HTML injection through URLs/filenames; the player must address exact bytes by identity, not by URL/path. |
| `api/main.py` `/media/{subpath:path}` | `FileResponse(os.path.join(LIBRARY_DIR, subpath))` | **Incompatible.** Path-addressed serving (no traversal guard, OS separators in URLs on Windows). Required: identity-addressed, hash-verified, eligibility-checked bytes. |
| Server defaults | Binds `0.0.0.0` | **Incompatible** with a local-only privacy boundary. |
| Human decisions / persistence / export / provenance display | Not present | Must be built regardless of shell. |

## Maintenance and licensing implications

- `gradio<4` resolves to **gradio 3.50.2 (63 packages** with requests/pandas on Python 3.11).
  GitHub's advisory database lists **41 advisories affecting gradio 3.50.2**: 3 critical,
  17 high, 18 medium, 3 low (queried 2026-10-01 via `gh api /advisories?ecosystem=pip&affects=gradio@3.50.2`).
  They include arbitrary file access, path traversal (including Windows-specific absolute path
  traversal and credential leakage on Windows), CORS/null-origin bypasses, SSRF and XSS.
- Moving to a supported line means current gradio (6.29.0, 51 packages) and a major API port of
  every component, which is no longer a bounded fork.
- SAS is MIT: copying code would only require the notice. No SAS code is copied, so no notice is
  needed; the concepts above are credited here.

## Decision

**Do not fork the SAS UI.** A bounded fork would retain only the table/player layout (about
30 lines) while requiring replacement of all six API callbacks, a Gradio major-version port,
new identity-addressed media serving, persistence, provenance display and export. That is
larger than the new interface and adds a heavy, advisory-prone dependency tree.

**Chosen boundary:** extend this repository's own Issue #6 audition server pattern
(`audio_selector/audition.py`: stdlib `http.server`, loopback bind, per-session write token,
Origin check, HTTP Range streaming, eligibility recheck per byte request; already validated in
Windows browsers for decode/seek) into `audio_selector/audition_queue.py` with a small static
UI (`audio_selector/ui/`). No new runtime dependency. SAS's retrieval/ranking path is not used
at all; Issue #7 `role-ranking-result/1.0` documents are the only ordering input.
