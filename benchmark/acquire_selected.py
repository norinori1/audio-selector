"""One-time acquisition of 13 manually selected individual assets, no discovery.

The reviewed fixed URLs below are replayable; no page parsing, crawling or pack
downloads. Copies the four explicitly reviewed evidence pages for audit only.
Once manifest exists, never refresh evidence/assertions: verify committed files.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request

from audio_selector.manifest import Blob, Manifest, evaluate, sha256

ROOT = Path(__file__).resolve().parent
UI_REV = "9950fe66f993a6660dab9c2651dcbcd899ffd83b"
CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"
UI = f"https://raw.githubusercontent.com/romainsimon/uisfx/{UI_REV}/"
OGA = "https://opengameart.org/sites/default/files/"
SOURCES = {
    "oga-spring": ("https://opengameart.org/content/various-sound-effects-0", "Spring Spring / Julie Damsgaard"),
    "oga-error": ("https://opengameart.org/content/error", "EZduzziteh"),
    "oga-searching": ("https://opengameart.org/content/searching", "yd"),
    "oga-etirwer": ("https://opengameart.org/content/etirwer", "Kistol"),
    "uisfx": (UI + "LICENSE-AUDIO", "Yuki Capital"),
}
SELECTED = [
    ("oga-menu-move", "oga-spring", OGA + "snd_menu_move.wav"),
    ("oga-menu-select", "oga-spring", OGA + "snd_menu_select.wav"),
    ("oga-footsteps", "oga-spring", OGA + "snd_footsteps1.wav"),
    ("oga-teleport", "oga-spring", OGA + "teleport_2.wav"),
    ("oga-door", "oga-spring", OGA + "powered_door.wav"),
    ("oga-item", "oga-spring", OGA + "get_important_item.wav"),
    ("oga-error", "oga-error", OGA + "error_0.ogg"),
    ("oga-searching", "oga-searching", OGA + "Searching.ogg"),
    ("oga-etirwer", "oga-etirwer", OGA + "Etirwer%20%28Looped%29_0.ogg"),
] + [(f"uisfx-{cue}", "uisfx", UI + f"packages/uisfx/sounds/arcade/{cue}.ogg")
     for cue in ["select", "success", "error", "level-up"]]


def fetch(url, path):
    if path.exists():
        return
    print("Download individual:", url, flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "audio-selector-small-research-corpus/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read(12_000_001)
    if len(content) > 12_000_000:
        raise ValueError("selected file exceeds bounded acquisition limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def blob(path, media_type):
    return dict(path=path.relative_to(ROOT).as_posix(), filename=path.name,
                sha256=sha256(path), size=path.stat().st_size, media_type=media_type)


def main():
    manifest_path = ROOT / "manifest.json"
    if manifest_path.exists():
        m = Manifest.model_validate_json(manifest_path.read_text())
        decisions = [evaluate(m, c.id, ROOT) for c in m.candidates]
        if any(d.status != "eligible" for d in decisions):
            raise ValueError("committed corpus has noneligible entries; inspect source evidence")
        print(f"Verified {len(decisions)} exact original assets; no network requests.")
        return
    now = datetime.now(timezone.utc).date().isoformat()
    snapshots = {}
    for source, (url, _) in SOURCES.items():
        path = ROOT / "evidence" / (source + (".txt" if source == "uisfx" else ".html"))
        fetch(url, path)
        snapshots[source] = blob(path, "text/plain" if source == "uisfx" else "text/html")
    fetch(CC0 + "legalcode.txt", ROOT / "evidence/cc0-legalcode.txt")
    candidates, scopes = [], {source: [] for source in SOURCES}
    for cid, source, url in SELECTED:
        from urllib.parse import unquote
        original_name = unquote(url.rsplit("/", 1)[-1])
        original_name = {"oga-teleport": "teleport.wav", "oga-error": "error.ogg",
                         "oga-etirwer": "Etirwer (Looped).ogg"}.get(cid, original_name)
        # Source-provided file, not a website preview or a converted rendition.
        path = ROOT / "media" / (cid + Path(original_name).suffix)
        fetch(url, path)
        original = blob(path, "audio/ogg" if path.suffix == ".ogg" else "audio/wav")
        original["filename"] = original_name
        scopes[source].append(original["sha256"])
        candidates.append(dict(id=cid, provider="UI SFX" if source == "uisfx" else "OpenGameArt",
            source_asset_id=f"{UI_REV}:packages/uisfx/sounds/arcade/{original_name}" if source == "uisfx" else url,
            asset_url=url, author=SOURCES[source][1], acquisition_source=SOURCES[source][0], acquired=now,
            metadata_evidence_ids=[source], original=original, preview=None, kind="original",
            rights=dict(license_name="CC0-1.0", license_url=CC0,
                evidence_ids=[source, "cc0-legalcode"], commercial="allowed", modification="allowed",
                game_embedding="allowed", redistribution="allowed", attribution="not-required",
                redistribution_restrictions="CC0 grant recorded; no additional asset restrictions stated. No endorsement implied.",
                content_id_notes="No Content ID registration or claim statement found in reviewed grant; absence of claims is not guaranteed.")))
    evidence = [dict(id=source, url=url, snapshot=snapshots[source], checked=now,
        asset_sha256s=scopes[source], notes="Individually reviewed source asset listing/grant on 2026-09-30. "
        + (f"Pinned repository {UI_REV}: LICENSE-AUDIO explicitly covers packages/uisfx/sounds, excludes .generated."
           if source == "uisfx" else "Page lists these exact attachment URLs under CC0; author and filenames retained. "
           "Grant interpretation explicitly entered for this small research corpus; not provider-wide eligibility."))
        for source, (url, _) in SOURCES.items()]
    evidence.append(dict(id="cc0-legalcode", url=CC0 + "legalcode.txt",
        snapshot=blob(ROOT / "evidence/cc0-legalcode.txt", "text/plain"), checked=now,
        asset_sha256s=[c["original"]["sha256"] for c in candidates],
        notes="CC0 legal terms combined with each asset-specific source grant, not standalone proof of an asset grant."))
    manifest = Manifest.model_validate(dict(schema_version="1.0", candidates=candidates, evidence=evidence))
    decisions = [evaluate(manifest, c.id, ROOT) for c in manifest.candidates]
    if any(d.status != "eligible" for d in decisions):
        raise ValueError([d.model_dump(mode="json") for d in decisions])
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (ROOT / "eligibility-at-preparation.json").write_text(
        json.dumps([d.model_dump(mode="json") for d in decisions], indent=2), encoding="utf-8")
    print(f"Acquired {len(candidates)} eligible originals; no previews acquired.")


if __name__ == "__main__":
    main()
