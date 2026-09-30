"""Loopback-only human audition queue over frozen Issue #7 rankings, with reproducible export.

Requests never name a filesystem path: audio is addressed by (ranking package, candidate)
and served only as verified exact bytes. The human makes every decision.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import unquote

from .contract import CONTRACT
from .manifest import Policy, load
from .ranking import load_config
from .selection import (Store, build_export, import_export, manifest_digest, provenance,
                        verified_bytes, verify, verify_export, write_export)

UI = Path(__file__).with_name("ui")
ASSETS = {"/": ("queue.html", "text/html; charset=utf-8"), "/queue.js": ("queue.js", "text/javascript"),
          "/queue.css": ("queue.css", "text/css")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; media-src 'self'; connect-src 'self'; "
       "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _record_view(record):
    if record is None:
        return None
    return dict(current=record.events[-1].decision, note=record.events[-1].note,
                decided_at=record.events[-1].decided_at.isoformat(), events=len(record.events))


def entry_view(entry, manifest, root, policy, record):
    status = verify(manifest, root, policy, entry["candidate_id"], entry["representation"], entry["sha256"])
    recorded = provenance(manifest, entry["candidate_id"]) if status["identity"] == "ok" else None
    if recorded is None and record is not None:
        # Show what was recorded when the human decided; never a different current file.
        recorded = record.events[-1].provenance
    return dict(entry, verification=status, recorded=recorded, decision=_record_view(record))


def state_view(store, manifest, root, policy, config_fingerprint):
    packages = []
    for p in store.state.packages:
        r = p.ranking

        def view(entry):
            record = store.record(p.package_id, entry["candidate_id"], entry["representation"])
            if record is not None and record.sha256 != entry["sha256"]:
                record = None
            return entry_view(entry, manifest, root, policy, record)
        packages.append(dict(package_id=p.package_id, added_at=p.added_at.isoformat(), query=r["query"],
            role_id=r["role_id"], ranking_config=r["ranking_config"], retrieval_contract=r["retrieval_contract"],
            index_state=r["index_state"], eligibility_policy_version=r["eligibility_policy_version"],
            diversity_implementation=r["diversity_implementation"],
            contract_matches_current=r["retrieval_contract"] == CONTRACT,
            config_matches_current=(None if config_fingerprint is None
                                    else r["ranking_config"]["fingerprint"] == config_fingerprint),
            queue=[view(e) for e in r["top_n"]], not_in_queue=[view(e) for e in r["beyond_top_n"]],
            suppressed=[dict(candidate_id=e["candidate_id"], sha256=e["sha256"], reasons=e["reranking"]["reasons"])
                        for e in r["suppressed"]], excluded=r["excluded"]))
    return dict(packages=packages, current=dict(retrieval_contract=CONTRACT, config_fingerprint=config_fingerprint,
                manifest_sha256=manifest_digest(manifest), eligibility_policy_version=policy.version))


def make_server(manifest_path: Path, state_path: Path, *, rankings=(), config_path=None, policy=Policy(),
                exports_dir=None, port=8766):
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    load(manifest_path)  # fail early on an invalid manifest
    store = Store(state_path)
    for ranking in rankings:
        store.add_package(json.loads(Path(ranking).read_text(encoding="utf-8")))
    config_fingerprint = load_config(config_path).fingerprint() if config_path else None
    exports_dir = exports_dir or state_path.parent / "exports"
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, content, kind="application/json", status=200, headers=None):
            if isinstance(content, (dict, list)):
                content = json.dumps(content, allow_nan=False).encode()
            elif isinstance(content, str):
                content, kind = content.encode(), "text/plain; charset=utf-8"
            self.send_response(status)
            for key, value in {"Content-Type": kind, "Content-Length": str(len(content)),
                               "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                               "Referrer-Policy": "no-referrer", "Content-Security-Policy": CSP,
                               **(headers or {})}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(content)

        def local_host(self):
            # Loopback bind plus Host check blocks DNS-rebinding access from other sites.
            port_ = self.server.server_port
            return self.headers.get("Host") in {f"127.0.0.1:{port_}", f"localhost:{port_}"}

        def do_GET(self):
            if not self.local_host():
                return self.send("Forbidden host", status=403)
            path = self.path.split("?", 1)[0]
            try:
                if path in ASSETS:
                    name, kind = ASSETS[path]
                    return self.send((UI / name).read_bytes(), kind)
                if path == "/api/state":
                    view = state_view(store, load(manifest_path), root, policy, config_fingerprint)
                    return self.send(dict(view, save_token=token))
                match = re.fullmatch(r"/api/audio/([0-9a-f]{64})/([^/]+)", path)
                if match:
                    return self.audio(match[1], unquote(match[2]))
            except (ValueError, OSError, KeyError) as exc:
                return self.send(str(exc), status=409)
            self.send("Not found", status=404)

        def audio(self, package_id, candidate_id):
            package = store.package(package_id)
            entry = next((e for e in (package.ranking["top_n"] + package.ranking["beyond_top_n"] if package else [])
                          if e["candidate_id"] == candidate_id), None)
            if entry is None:
                return self.send("Not found", status=404)
            data, kind = verified_bytes(load(manifest_path), root, policy, candidate_id,
                                        entry["representation"], entry["sha256"])
            start, end, status, headers = 0, len(data) - 1, 200, {"Accept-Ranges": "bytes"}
            byte_range = self.headers.get("Range")
            if byte_range:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", byte_range)
                if not match or int(match[1]) > end:
                    return self.send(b"", status=416, headers={"Content-Range": f"bytes */{len(data)}"})
                start, end = int(match[1]), min(int(match[2]) if match[2] else end, end)
                if start > end:
                    return self.send(b"", status=416, headers={"Content-Range": f"bytes */{len(data)}"})
                status, headers["Content-Range"] = 206, f"bytes {start}-{end}/{len(data)}"
            self.send(data[start:end + 1], kind, status, headers)

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if (not self.local_host() or self.headers.get("X-Audition-Token") != token
                    or (origin and origin not in allowed)):
                return self.send("Forbidden", status=403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 2 or length > 100_000:
                    raise ValueError("invalid payload size")
                body = json.loads(self.rfile.read(length))
                manifest = load(manifest_path)
                if self.path == "/api/decision":
                    if set(body) != {"package_id", "candidate_id", "representation", "sha256", "decision", "note"}:
                        raise ValueError("decision payload must name the exact identity, decision and note")
                    record = store.decide(manifest, root, policy, package_id=body["package_id"],
                        candidate_id=body["candidate_id"], representation=body["representation"],
                        sha256=body["sha256"], decision=body["decision"], note=body["note"] or "")
                    return self.send(dict(saved=_record_view(record)))
                if self.path == "/api/export":
                    export = build_export(store.state, manifest, root, policy)
                    path = write_export(export, exports_dir)
                    return self.send(dict(export=export, saved_as=path.name))
            except KeyError:
                return self.send("Unknown ranking package", status=404)
            except (ValueError, OSError) as exc:
                return self.send(str(exc), status=409)
            self.send("Not found", status=404)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["serve", "export", "verify-export", "import"])
    parser.add_argument("export_file", type=Path, nargs="?")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path("outputs/audition/state.json"))
    parser.add_argument("--ranking", type=Path, action="append", default=[])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--exports", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args()
    policy = Policy.model_validate_json(args.policy.read_text()) if args.policy else Policy()
    root = args.manifest.resolve().parent
    try:
        if args.action == "serve":
            server = make_server(args.manifest, args.state.resolve(), rankings=args.ranking,
                                 config_path=args.config, policy=policy, exports_dir=args.exports, port=args.port)
            print(f"Audition queue: http://127.0.0.1:{server.server_port}/", flush=True)
            print(f"Decisions persist in {args.state}; you make every decision.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return
        manifest = load(args.manifest)
        if args.action == "export":
            export = build_export(Store(args.state).state, manifest, root, policy)
            path = write_export(export, args.exports or args.state.parent / "exports")
            print(json.dumps(dict(saved_as=str(path), integrity=export["integrity"]), indent=2))
            if args.require_verified and not export["integrity"]["selected_verified"]:
                sys.exit(3)
            return
        if not args.export_file:
            parser.error(f"{args.action} requires an export file")
        export = json.loads(args.export_file.read_text(encoding="utf-8"))
        fingerprint = load_config(args.config).fingerprint() if args.config else None
        report = verify_export(export, manifest, root, policy, config_fingerprint=fingerprint)
        result = dict(report=report)
        if args.action == "import":
            result["import"] = import_export(Store(args.state), export)
        print(json.dumps(result, indent=2))
        if not report["verified"]:
            sys.exit(3)
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
