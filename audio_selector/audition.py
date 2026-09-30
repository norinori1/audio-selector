"""Loopback-only blinded human audition; no model scores are served."""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .manifest import eligible_candidates, evaluate, load


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    clip_id: str
    relevance: Literal["relevant", "irrelevant", "unsure"]
    audition_seconds: float = Field(gt=0, allow_inf_nan=False)
    play_count: int = Field(ge=1)
    notes: str = Field(default="", max_length=4000)


def validate_labels(payload, session):
    if set(payload) != {"package_id", "judgments"} or payload["package_id"] != session["package_id"]:
        raise ValueError("labels belong to a different benchmark package")
    allowed = {(q["id"], c["clip_id"]) for q in session["queries"] for c in q["clips"]}
    seen, validated = set(), []
    for raw in payload["judgments"]:
        item = Judgment.model_validate(raw)
        key = (item.query_id, item.clip_id)
        if key not in allowed or key in seen:
            raise ValueError("unknown/duplicate judgment")
        seen.add(key)
        validated.append(item.model_dump())
    return dict(package_id=payload["package_id"], judgments=validated)


def make_server(root: Path, labels: Path, port=8765):
    manifest = load(root / "manifest.json")
    eligible = eligible_candidates(manifest, root)
    if len(eligible) != len(manifest.candidates) or not eligible:
        raise ValueError("audition corpus is no longer entirely eligible; review before listening")
    session = json.loads((root / "prepared/session.json").read_text())
    mapping = json.loads((root / "prepared/blind-map.json").read_text())
    by_id = {c.id: c for c in eligible}
    paths = {}
    for q in session["queries"]:
        candidate_ids = []
        for clip in q["clips"]:
            ref = mapping[clip["clip_id"]]
            c = by_id[ref["candidate_id"]]
            if ref["query_id"] != q["id"] or ref["original_sha256"] != c.original.sha256:
                raise ValueError("stale blind mapping")
            candidate_ids.append(c.id)
            paths[clip["clip_id"]] = root / c.original.path
        if sorted(candidate_ids) != sorted(by_id):
            raise ValueError("incomplete or duplicate audition pool")
    # Fingerprint calculation imported lazily to keep launch free of model imports.
    import hashlib
    expected = hashlib.sha256(json.dumps(dict(manifest=manifest.model_dump(mode="json"),
        queries=json.loads((root / "queries.json").read_text()), protocol="full-corpus-blind/v1"),
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if session["package_id"] != expected:
        raise ValueError("stale preparation; regenerate benchmark before collecting labels")
    token = secrets.token_urlsafe(32)
    existing = dict(package_id=session["package_id"], judgments=[])
    if labels.exists():
        existing = validate_labels(json.loads(labels.read_text()), session)

    def current_corpus():
        current = load(root / "manifest.json")
        if current != manifest:
            raise ValueError("manifest changed during audition; restart with matching preparation")
        return current

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, content, kind="application/json", status=200, headers=None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.path == "/session":
                self.send(json.dumps(dict(**session, save_token=token)).encode())
            elif self.path == "/labels":
                self.send(json.dumps(existing).encode())
            elif self.path in ["/", "/app.js"]:
                path = root / ("audition.html" if self.path == "/" else "app.js")
                self.send(path.read_bytes(), "text/html; charset=utf-8" if self.path == "/" else "text/javascript")
            elif self.path.startswith("/clip/") and self.path[6:] in paths:
                # Anonymous original-byte endpoint; source names and ranking are absent.
                try:
                    current = current_corpus()
                    ref = mapping[self.path[6:]]
                    if evaluate(current, ref["candidate_id"], root).status != "eligible":
                        raise ValueError("clip no longer eligible")
                except (ValueError, OSError, KeyError) as exc:
                    self.send(str(exc).encode(), "text/plain", 409)
                    return
                path = paths[self.path[6:]]
                size, start, end = path.stat().st_size, 0, path.stat().st_size - 1
                status, headers = 200, {"Accept-Ranges": "bytes"}
                byte_range = self.headers.get("Range")
                if byte_range:
                    match = re.fullmatch(r"bytes=(\d+)-(\d*)", byte_range)
                    if not match:
                        self.send(b"", status=416)
                        return
                    start = int(match[1])
                    end = min(int(match[2]) if match[2] else end, end)
                    if start > end:
                        self.send(b"", status=416)
                        return
                    status = 206
                    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
                with path.open("rb") as stream:
                    stream.seek(start)
                    self.send(stream.read(end-start+1), mimetypes.guess_type(path.name)[0] or "audio/ogg", status, headers)
            else:
                self.send(b"Not found", "text/plain", 404)

        def do_POST(self):
            nonlocal existing
            origin = self.headers.get("Origin")
            allowed_origin = f"http://127.0.0.1:{self.server.server_port}"
            if (self.path != "/labels" or self.headers.get("X-Audition-Token") != token
                or (origin and origin != allowed_origin)):
                self.send(b"Forbidden", "text/plain", 403)
                return
            try:
                current = current_corpus()
                if len(eligible_candidates(current, root)) != len(current.candidates):
                    raise ValueError("corpus eligibility changed; preserve previous labels and review evidence")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 2_000_000:
                    raise ValueError("invalid label payload size")
                incoming = validate_labels(json.loads(self.rfile.read(length)), session)
                labels.parent.mkdir(parents=True, exist_ok=True)
                temp = labels.with_suffix(".tmp")
                temp.write_text(json.dumps(incoming, indent=2), encoding="utf-8")
                temp.replace(labels)
                existing = incoming
                self.send(json.dumps(dict(saved=len(existing["judgments"]))).encode())
            except (ValueError, OSError) as exc:
                self.send(str(exc).encode(), "text/plain", 400)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("benchmark"))
    parser.add_argument("--labels", type=Path, default=Path("outputs/benchmark/labels.json"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = make_server(args.root.resolve(), args.labels.resolve(), args.port)
    print(f"HUMAN AUDITION REQUIRED: open http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Labels saved only after your judgments: {args.labels.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
