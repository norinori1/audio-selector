"""Issue #8 audition queue: persistence, exact identity, export/import and local boundaries."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from audio_selector.audition_queue import make_server
from audio_selector.manifest import load
from audio_selector.ranking import canonical_sha256
from audio_selector.selection import (Store, build_export, import_export, verify_export, write_export)

BENCH = Path(__file__).resolve().parents[1] / "benchmark"
RANKINGS = json.loads((BENCH / "evaluation/role-rankings-v1.json").read_text())
CONFIG = BENCH / "roles/ranking-v1.json"


def corpus(parent: Path):
    # Windows path handling: spaces and non-ASCII in the manifest directory.
    root = parent / "audition corpus ü"
    shutil.copytree(BENCH / "media", root / "media")
    shutil.copytree(BENCH / "evidence", root / "evidence")
    shutil.copy(BENCH / "manifest.json", root / "manifest.json")
    return root


def entry(ranking, candidate_id):
    return next(e for e in ranking["top_n"] + ranking["beyond_top_n"] if e["candidate_id"] == candidate_id)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = corpus(Path(self.tmp.name))
        self.state = Path(self.tmp.name) / "state dir" / "state.json"
        self.rankings = []
        for qid in ["q02", "q08"]:
            path = Path(self.tmp.name) / f"{qid}.json"
            path.write_text(json.dumps(RANKINGS[qid]))
            self.rankings.append(path)
        self.pkg = {qid: canonical_sha256(RANKINGS[qid]) for qid in ["q02", "q08"]}

    def manifest(self):
        return load(self.root / "manifest.json")

    def edit_manifest(self, change):
        data = json.loads((self.root / "manifest.json").read_text())
        change(data)
        (self.root / "manifest.json").write_text(json.dumps(data))

    def decide(self, store, qid, cid, decision, note=""):
        e = entry(RANKINGS[qid], cid)
        from audio_selector.manifest import Policy
        return store.decide(self.manifest(), self.root, Policy(), package_id=self.pkg[qid], candidate_id=cid,
                            representation=e["representation"], sha256=e["sha256"], decision=decision, note=note)


class StoreTests(Fixture):
    def test_packages_are_verbatim_issue7_rankings_bound_by_hash(self):
        store = Store(self.state)
        pid = store.add_package(RANKINGS["q02"])
        self.assertEqual(pid, self.pkg["q02"])
        self.assertEqual(Store(self.state).package(pid).ranking, RANKINGS["q02"])
        raw = json.loads(self.state.read_text())
        raw["packages"][0]["ranking"]["top_n"].reverse()
        self.state.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "does not match its package_id"):
            Store(self.state)

    def test_decisions_survive_restart_with_history_and_no_prefill(self):
        store = Store(self.state)
        store.add_package(RANKINGS["q02"])
        self.assertEqual(store.state.records, [])
        self.decide(store, "q02", "uisfx-select", "maybe", "check in context")
        self.decide(store, "q02", "uisfx-select", "accept", "fits menu")
        self.decide(store, "q02", "oga-menu-select", "reject")
        reopened = Store(self.state)
        record = reopened.record(self.pkg["q02"], "uisfx-select", "original")
        self.assertEqual([e.decision for e in record.events], ["maybe", "accept"])
        self.assertEqual(record.events[-1].note, "fits menu")
        self.assertEqual(record.sha256, entry(RANKINGS["q02"], "uisfx-select")["sha256"])
        self.assertEqual(record.events[-1].provenance["candidate"]["id"], "uisfx-select")

    def test_identity_must_match_ranking_package(self):
        store = Store(self.state)
        store.add_package(RANKINGS["q02"])
        from audio_selector.manifest import Policy
        with self.assertRaisesRegex(ValueError, "not part of this ranking package"):
            store.decide(self.manifest(), self.root, Policy(), package_id=self.pkg["q02"],
                         candidate_id="uisfx-select", representation="original", sha256="0" * 64, decision="accept")
        with self.assertRaises(KeyError):
            store.decide(self.manifest(), self.root, Policy(), package_id="f" * 64, candidate_id="uisfx-select",
                         representation="original", sha256="0" * 64, decision="accept")

    def test_missing_changed_and_ineligible_cannot_be_selected_or_substituted(self):
        store = Store(self.state)
        store.add_package(RANKINGS["q02"])
        (self.root / "media/uisfx-select.ogg").unlink()
        with self.assertRaisesRegex(ValueError, "local file missing"):
            self.decide(store, "q02", "uisfx-select", "accept")
        rejected = self.decide(store, "q02", "uisfx-select", "reject", "file gone")
        self.assertEqual(rejected.events[-1].verification["file"], "missing")
        # Same filename-like content from another candidate is never an acceptable substitute.
        shutil.copy(self.root / "media/uisfx-success.ogg", self.root / "media/uisfx-select.ogg")
        with self.assertRaisesRegex(ValueError, "local bytes changed"):
            self.decide(store, "q02", "uisfx-select", "shortlist")
        self.edit_manifest(lambda d: d["candidates"][1]["rights"].update(commercial="denied"))
        with self.assertRaisesRegex(ValueError, "eligibility now ineligible"):
            self.decide(store, "q02", "oga-menu-select", "maybe")


class ExportImportTests(Fixture):
    def populated(self):
        store = Store(self.state)
        for path in self.rankings:
            store.add_package(json.loads(path.read_text()))
        self.decide(store, "q02", "uisfx-select", "accept", "menu confirm")
        self.decide(store, "q02", "oga-menu-select", "shortlist")
        self.decide(store, "q02", "uisfx-error", "reject", "too harsh")
        self.decide(store, "q08", "oga-searching", "maybe", "check loop point")
        self.decide(store, "q08", "oga-etirwer", "accept")
        self.decide(store, "q08", "oga-etirwer", None)
        return store

    def test_export_contains_reproducible_identity(self):
        from audio_selector.manifest import Policy
        export = build_export(self.populated().state, self.manifest(), self.root, Policy())
        self.assertEqual(export["schema_version"], "audition-selection-export/1.0")
        self.assertEqual(export["content_sha256"], canonical_sha256({k: v for k, v in export.items() if k != "content_sha256"}))
        self.assertEqual(len(export["selections"]), 4)  # cleared decision is not exported as a selection
        s = next(x for x in export["selections"] if x["candidate_id"] == "uisfx-select")
        self.assertEqual((s["decision"], s["note"], s["representation"]), ("accept", "menu confirm", "original"))
        self.assertEqual(s["sha256"], hashlib.sha256((self.root / "media/uisfx-select.ogg").read_bytes()).hexdigest())
        self.assertEqual({e["id"] for e in s["provenance_at_decision"]["evidence"]}, {"uisfx", "cc0-legalcode"})
        self.assertEqual(s["eligibility_at_decision"]["status"], "eligible")
        self.assertEqual(s["ranking_context"]["retrieval_contract"]["revision"], "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a")
        self.assertEqual(s["ranking_context"]["ranking_config"]["version"], "1.0.0")
        self.assertIn("contributions", s["score"])
        self.assertTrue(export["integrity"]["all_verified"])
        self.assertEqual(len(export["packages"]), 2)
        text = json.dumps(export)
        for private in [str(self.root), str(self.root).replace("\\", "\\\\"), str(Path.home())]:
            self.assertNotIn(private, text)

    def test_roundtrip_import_restores_exact_state(self):
        from audio_selector.manifest import Policy
        store = self.populated()
        export = build_export(store.state, self.manifest(), self.root, Policy())
        path = write_export(export, self.state.parent / "exports")
        with self.assertRaises(FileExistsError):
            write_export(export, self.state.parent / "exports")  # historical files are never overwritten
        loaded = json.loads(path.read_text(encoding="utf-8"))
        report = verify_export(loaded, self.manifest(), self.root, Policy(),
                               config_fingerprint=json.loads(json.dumps(RANKINGS["q02"]))["ranking_config"]["fingerprint"])
        self.assertTrue(report["verified"], report)
        fresh = Store(Path(self.tmp.name) / "fresh" / "state.json")
        summary = import_export(fresh, loaded)
        self.assertEqual((summary["packages_added"], summary["records_added"], summary["conflicts"]), (2, 4, []))
        self.assertEqual(import_export(fresh, loaded)["unchanged"], 4)
        imported = {r.key(): r for r in Store(fresh.path).state.records}
        original = {r.key(): r for r in store.state.records if r.events[-1].decision is not None}
        self.assertEqual(imported, original)
        again = build_export(Store(fresh.path).state, self.manifest(), self.root, Policy())
        strip = lambda e: [{k: v for k, v in s.items() if k != "verification_at_export"} for s in e["selections"]]
        self.assertEqual(strip(again), strip(export))
        self.assertEqual(again["packages"], export["packages"])

    def test_mismatches_are_reported_explicitly(self):
        from audio_selector.manifest import Policy
        export = build_export(self.populated().state, self.manifest(), self.root, Policy())
        tampered = json.loads(json.dumps(export))
        tampered["selections"][0]["decision"] = "reject"
        self.assertIn("content_sha256 mismatch: export was edited or corrupted",
                      verify_export(tampered, self.manifest(), self.root, Policy())["global_issues"])
        with self.assertRaisesRegex(ValueError, "modified export"):
            import_export(Store(Path(self.tmp.name) / "t.json"), tampered)
        with patch("audio_selector.selection.CONTRACT", {"revision": "other"}):
            report = verify_export(export, self.manifest(), self.root, Policy(), config_fingerprint="0" * 64)
        self.assertTrue(all({"model_contract", "ranking_config"} <= set(s["mismatches"]) for s in report["selections"]))
        (self.root / "media/uisfx-select.ogg").write_bytes(b"changed")
        self.edit_manifest(lambda d: d["evidence"][0].update(notes="evidence text revised"))
        self.edit_manifest(lambda d: d["candidates"][1]["rights"].update(commercial="denied"))
        report = verify_export(export, self.manifest(), self.root, Policy())
        by_id = {s["candidate_id"]: set(s["mismatches"]) for s in report["selections"]}
        self.assertFalse(report["verified"])
        self.assertIn("bytes", by_id["uisfx-select"])
        self.assertIn("eligibility", by_id["oga-menu-select"])
        self.assertIn("provenance", by_id["oga-menu-select"])  # oga-spring evidence record changed
        self.assertEqual(by_id["uisfx-error"], set())
        self.edit_manifest(lambda d: d.update(candidates=[c for c in d["candidates"] if c["id"] != "oga-searching"]))
        report = verify_export(export, self.manifest(), self.root, Policy())
        searching = next(s for s in report["selections"] if s["candidate_id"] == "oga-searching")
        self.assertIn("identity", searching["mismatches"])

    def test_historical_export_is_unchanged_and_new_export_flags(self):
        from audio_selector.manifest import Policy
        store = self.populated()
        first = write_export(build_export(store.state, self.manifest(), self.root, Policy()), self.state.parent / "x")
        before = first.read_bytes()
        (self.root / "media/oga-searching.ogg").unlink()
        self.decide(store, "q02", "uisfx-success", "maybe")
        later = build_export(store.state, self.manifest(), self.root, Policy())
        self.assertEqual(first.read_bytes(), before)
        self.assertFalse(later["integrity"]["all_verified"])
        self.assertFalse(later["integrity"]["selected_verified"])  # maybe on a missing file
        self.assertEqual([f["candidate_id"] for f in later["integrity"]["flagged"]], ["oga-searching"])

    def test_import_never_overwrites_a_different_history(self):
        from audio_selector.manifest import Policy
        store = self.populated()
        export = build_export(store.state, self.manifest(), self.root, Policy())
        self.decide(store, "q02", "uisfx-select", "reject", "changed my mind")
        summary = import_export(store, export)
        self.assertEqual([c["candidate_id"] for c in summary["conflicts"]], ["uisfx-select"])
        self.assertEqual(Store(self.state).record(self.pkg["q02"], "uisfx-select", "original").events[-1].decision, "reject")

    def test_cli_export_verify_import_exit_codes(self):
        self.populated()
        base = [sys.executable, "-m", "audio_selector.audition_queue"]
        common = ["--manifest", str(self.root / "manifest.json"), "--state", str(self.state)]
        done = subprocess.run(base + ["export", *common, "--require-verified"], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        path = Path(json.loads(done.stdout)["saved_as"])
        done = subprocess.run(base + ["verify-export", str(path), *common, "--config", str(CONFIG)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        fresh = ["--manifest", str(self.root / "manifest.json"), "--state", str(Path(self.tmp.name) / "n" / "s.json")]
        done = subprocess.run(base + ["import", str(path), *fresh], capture_output=True, text=True, timeout=120)
        self.assertEqual((done.returncode, json.loads(done.stdout)["import"]["records_added"]), (0, 4), done.stderr)
        (self.root / "media/uisfx-select.ogg").unlink()
        done = subprocess.run(base + ["export", *common, "--require-verified"], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 3)
        done = subprocess.run(base + ["verify-export", str(path), *common], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 3)


class ServerTests(Fixture):
    def start(self, **kwargs):
        server = make_server(self.root / "manifest.json", self.state, rankings=self.rankings, port=0, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.url = f"http://127.0.0.1:{server.server_port}"

        def stop():
            server.shutdown()
            server.server_close()
            thread.join()
        return stop

    def get(self, path, headers=None):
        with urllib.request.urlopen(urllib.request.Request(self.url + path, headers=headers or {})) as r:
            return r.status, r.headers, r.read()

    def post(self, path, payload, token, headers=None):
        request = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-Audition-Token": token, **(headers or {})})
        with urllib.request.urlopen(request) as r:
            return json.load(r)

    def status_of(self, path, **kwargs):
        try:
            return self.get(path, **kwargs)[0]
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_queue_view_audio_decisions_restart_and_boundaries(self):
        stop = self.start(config_path=CONFIG)
        try:
            state = json.loads(self.get("/api/state")[2])
            token = state["save_token"]
            q02, q08 = (next(p for p in state["packages"] if p["package_id"] == self.pkg[q]) for q in ["q02", "q08"])
            self.assertEqual([e["candidate_id"] for e in q02["queue"]], [e["candidate_id"] for e in RANKINGS["q02"]["top_n"]])
            self.assertTrue(q02["config_matches_current"] and q02["contract_matches_current"])
            first = q02["queue"][0]
            for key in ["rank", "sha256", "provider", "author", "representation", "contributions", "reranking",
                        "pre_diversity_score", "signals", "eligibility", "verification", "recorded"]:
                self.assertIn(key, first)
            self.assertTrue(all(e["decision"] is None for e in q02["queue"] + q02["not_in_queue"]))
            self.assertTrue(first["verification"]["playable"])
            # Short SFX: exact bytes and ranges.
            path = f"/api/audio/{self.pkg['q02']}/{first['candidate_id']}"
            data = (self.root / "media" / f"{first['candidate_id']}.ogg").read_bytes()
            self.assertEqual(self.get(path)[2], data)
            status, headers, part = self.get(path, {"Range": "bytes=0-99"})
            self.assertEqual((status, part, headers["Content-Range"]), (206, data[:100], f"bytes 0-99/{len(data)}"))
            # Long BGM: mid-file seek range.
            bgm = q08["queue"][0]
            self.assertGreater(bgm["signals"]["dsp"]["duration_seconds"], 60)
            big = (self.root / "media" / f"{bgm['candidate_id']}.ogg").read_bytes()
            mid = len(big) // 2
            status, headers, part = self.get(f"/api/audio/{self.pkg['q08']}/{bgm['candidate_id']}",
                                             {"Range": f"bytes={mid}-"})
            self.assertEqual((status, part), (206, big[mid:]))
            self.assertEqual(self.status_of(f"/api/audio/{self.pkg['q08']}/x", headers={"Range": f"bytes={len(big)*2}-"}), 404)
            saved = self.post("/api/decision", dict(package_id=self.pkg["q02"], candidate_id=first["candidate_id"],
                representation="original", sha256=first["sha256"], decision="shortlist", note="n"), token)
            self.assertEqual(saved["saved"]["current"], "shortlist")
            exported = self.post("/api/export", {}, token)
            self.assertTrue((self.state.parent / "exports" / exported["saved_as"]).exists())
            # Boundaries: token, origin, host, traversal, private paths.
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.post("/api/decision", {}, "wrong")
            self.assertEqual(exc.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.post("/api/export", {}, token, {"Origin": "http://evil.example"})
            self.assertEqual(exc.exception.code, 403)
            self.assertEqual(self.status_of("/api/state", headers={"Host": "evil.example"}), 403)
            for probe in ["/manifest.json", "/media/oga-door.wav", "/../manifest.json",
                          f"/api/audio/{self.pkg['q02']}/..%2F..%2Fmanifest.json", "/api/audio/x/y"]:
                self.assertEqual(self.status_of(probe), 404, probe)
            body = self.get("/api/state")[2].decode()
            for private in [str(self.root), json.dumps(str(self.root))[1:-1], str(Path.home())]:
                self.assertNotIn(private, body)
            headers = self.get("/")[1]
            self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        finally:
            stop()
        # Restart: decision persists; changed files are detected; blocked assets are not served.
        (self.root / "media/uisfx-success.ogg").unlink()
        shutil.copy(self.root / "media/uisfx-level-up.ogg", self.root / "media/uisfx-error.ogg")
        self.edit_manifest(lambda d: d["candidates"][1]["rights"].update(commercial="denied"))
        other = Path(self.tmp.name) / "other-config.json"
        changed = json.loads(CONFIG.read_text())
        changed["version"] = "1.0.1"
        other.write_text(json.dumps(changed))
        stop = self.start(config_path=other)
        try:
            state = json.loads(self.get("/api/state")[2])
            q02 = next(p for p in state["packages"] if p["package_id"] == self.pkg["q02"])
            views = {e["candidate_id"]: e for e in q02["queue"] + q02["not_in_queue"]}
            self.assertEqual(views[first["candidate_id"]]["decision"]["current"], "shortlist")
            self.assertFalse(q02["config_matches_current"])
            self.assertEqual(views["uisfx-success"]["verification"]["file"], "missing")
            self.assertEqual(views["uisfx-error"]["verification"]["file"], "hash-changed")
            self.assertEqual(views["oga-menu-select"]["verification"]["eligibility"]["status"], "ineligible")
            for cid in ["uisfx-success", "uisfx-error", "oga-menu-select"]:
                self.assertFalse(views[cid]["verification"]["playable"])
                self.assertEqual(self.status_of(f"/api/audio/{self.pkg['q02']}/{cid}"), 409)
                self.assertIsNotNone(views[cid]["recorded"])
            with self.assertRaises(urllib.error.HTTPError) as exc:
                e = views["uisfx-error"]
                self.post("/api/decision", dict(package_id=self.pkg["q02"], candidate_id="uisfx-error",
                    representation="original", sha256=e["sha256"], decision="accept", note=""), state["save_token"])
            self.assertEqual(exc.exception.code, 409)
        finally:
            stop()


if __name__ == "__main__":
    unittest.main()
