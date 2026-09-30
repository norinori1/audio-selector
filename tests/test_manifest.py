from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pydantic import ValidationError
from audio_selector.manifest import Blob, Manifest, Policy, evaluate, sha256

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def fixture(root):
    (root / "original.wav").write_bytes(b"illustrative original, not playable audio")
    (root / "preview.wav").write_bytes(b"different preview bytes")
    (root / "evidence.txt").write_text("Illustrative assertion only; not real asset rights.")
    def blob(name):
        path = root / name
        return dict(path=name, filename=name, sha256=sha256(path), size=path.stat().st_size,
                    media_type="audio/wav" if name.endswith("wav") else "text/plain")
    original, preview, snapshot = map(blob, ["original.wav", "preview.wav", "evidence.txt"])
    return dict(schema_version="1.0", evidence=[dict(id="e1", url="https://example.org/evidence",
        snapshot=snapshot, checked="2026-09-30", asset_sha256s=[original["sha256"]],
        notes="Test assertion, never real acquisition evidence")], candidates=[dict(
        id="asset-1", provider="test", source_asset_id="1", asset_url="https://example.org/1",
        author="test", acquisition_source="unit fixture", acquired="2026-09-30",
        metadata_evidence_ids=["e1"], original=original, preview=preview,
        rights=dict(license_name="test grant", license_url="https://example.org/license",
            evidence_ids=["e1"], commercial="allowed", modification="allowed",
            game_embedding="allowed", redistribution="allowed", attribution="not-required",
            redistribution_restrictions="none recorded", content_id_notes="none recorded"))])


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = fixture(self.root)

    def decision(self, policy=Policy(), **kwargs):
        return evaluate(Manifest.model_validate(self.data), "asset-1", self.root, policy,
                        now=NOW, **kwargs)

    def test_permissive_and_hash_identity(self):
        self.assertEqual(self.decision().status, "eligible")
        c = Manifest.model_validate(self.data).candidates[0]
        self.assertNotEqual(c.original.sha256, c.preview.sha256)

    def test_every_unknown_and_denied_required_right(self):
        for key in ["commercial", "game_embedding"]:
            for value, status in [("unknown", "review-required"), ("denied", "ineligible")]:
                with self.subTest(key=key, value=value):
                    self.data = fixture(self.root)
                    self.data["candidates"][0]["rights"][key] = value
                    self.assertEqual(self.decision().status, status)

    def test_missing_rights_and_obligations(self):
        self.data["candidates"][0]["rights"] = None
        self.assertEqual(self.decision().status, "review-required")
        self.data = fixture(self.root)
        rights = self.data["candidates"][0]["rights"]
        rights["attribution"] = "required"
        rights["attribution_text"] = "Credit test"
        self.assertEqual(self.decision().status, "review-required")
        self.assertEqual(self.decision(Policy(fulfilled_attribution_ids={"asset-1"})).status, "eligible")
        rights["content_id_notes"] = None
        self.assertEqual(self.decision(Policy(fulfilled_attribution_ids={"asset-1"})).status, "review-required")

    def test_stale_future_missing_changed_unbound_evidence(self):
        for checked in ["2020-01-01", "2027-01-01"]:
            self.data["evidence"][0]["checked"] = checked
            self.assertEqual(self.decision().status, "review-required")
        self.data = fixture(self.root)
        self.data["evidence"][0]["asset_sha256s"] = ["0" * 64]
        self.assertEqual(self.decision().status, "review-required")
        self.data = fixture(self.root)
        (self.root / "evidence.txt").write_text("tampered")
        self.assertEqual(self.decision().status, "review-required")
        (self.root / "evidence.txt").unlink()
        self.assertEqual(self.decision().status, "review-required")

    def test_preview_never_inherits_original_grant(self):
        self.assertEqual(self.decision(representation="preview").status, "ineligible")
        self.assertEqual(self.decision(Policy(allow_preview=True), representation="preview").status,
                         "review-required")

    def test_changed_or_missing_original(self):
        (self.root / "original.wav").write_bytes(b"tampered")
        self.assertEqual(self.decision().status, "review-required")
        (self.root / "original.wav").unlink()
        self.assertEqual(self.decision().status, "review-required")

    def test_lineage_checks_parent_modification(self):
        parent = self.data["candidates"][0]
        child = json.loads(json.dumps(parent))
        child.update(id="child", kind="derivative", parent_id="asset-1", transformation="test edit")
        self.data["candidates"].append(child)
        m = Manifest.model_validate(self.data)
        self.assertEqual(evaluate(m, "child", self.root, now=NOW).status, "eligible")
        parent["rights"]["modification"] = "denied"
        m = Manifest.model_validate(self.data)
        self.assertNotEqual(evaluate(m, "child", self.root, now=NOW).status, "eligible")
        parent.update(kind="derivative", parent_id="child", transformation="cycle")
        with self.assertRaises(ValidationError):
            Manifest.model_validate(self.data)

    def test_structural_invalid_and_forged_decision(self):
        for mutation in [lambda d: d["candidates"].append(d["candidates"][0]),
                         lambda d: d["evidence"].clear(),
                         lambda d: d["candidates"][0].update(eligibility="eligible"),
                         lambda d: d["candidates"][0]["original"].update(sha256="bad")]:
            self.data = fixture(self.root)
            mutation(self.data)
            with self.assertRaises(ValidationError):
                Manifest.model_validate(self.data)

    def test_cli_exit_codes(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.data))
        def run(*args):
            return subprocess.run([sys.executable, "-m", "audio_selector.manifest", str(manifest),
                                   *args], capture_output=True).returncode
        self.assertEqual(run("--require-all-eligible"), 0)
        self.data["candidates"][0]["rights"] = None
        manifest.write_text(json.dumps(self.data))
        self.assertEqual(run("--require-all-eligible"), 3)
        manifest.write_text("{}")
        self.assertEqual(run(), 2)
        manifest.write_text(json.dumps(self.data))
        (self.root / "original.wav").unlink()
        self.assertEqual(run(), 2)


if __name__ == "__main__":
    unittest.main()
