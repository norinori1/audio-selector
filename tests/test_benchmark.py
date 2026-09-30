"""Protocol/data-integrity tests; no corpus human judgments are created."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from audio_selector.audition import make_server, validate_labels
from audio_selector.benchmark_metrics import calculate, retrieval_metrics
from audio_selector.manifest import eligible_candidates, load, sha256

ROOT = Path(__file__).resolve().parents[1] / "benchmark"


class MetricMathTests(unittest.TestCase):
    def test_standard_multiple_positive_arithmetic(self):
        # Abstract binary relevance math, not audition labels or benchmark results.
        self.assertEqual(retrieval_metrics([1, 0, 1], 3, 2)["recall"], 1)
        self.assertAlmostEqual(retrieval_metrics([1, 0, 1], 3, 2)["ap"], (1+2/3)/2)
        self.assertEqual(retrieval_metrics([1, 0, 1], 1, 2)["recall"], 0.5)
        self.assertEqual(retrieval_metrics([0, 0], 2, 2)["ap"], 0)
        self.assertIsNone(retrieval_metrics([0, 0], 2, 0)["ap"])


class BenchmarkIntegrityTests(unittest.TestCase):
    def test_entire_real_corpus_is_eligible(self):
        manifest = load(ROOT / "manifest.json")
        self.assertEqual(len(eligible_candidates(manifest, ROOT)), 13)
        self.assertEqual(len({c.provider for c in manifest.candidates}), 2)
        self.assertTrue(all(c.preview is None for c in manifest.candidates))

    def test_predictions_scope_and_no_ranking_leaks(self):
        session = json.loads((ROOT / "prepared/session.json").read_text())
        predictions = json.loads((ROOT / "prepared/predictions.json").read_text())
        self.assertEqual(session["package_id"], predictions["package_id"])
        self.assertEqual(sum(len(q["clips"]) for q in session["queries"]), 156)
        candidate_ids = {c.id for c in load(ROOT / "manifest.json").candidates}
        mapping = json.loads((ROOT / "prepared/blind-map.json").read_text())
        for q in session["queries"]:
            self.assertEqual(set(q), {"id", "prompt", "clips"})
            for clip in q["clips"]:
                self.assertEqual(set(clip), {"clip_id", "duration"})
            for method in predictions["queries"][q["id"]].values():
                self.assertTrue({h["candidate_id"] for h in method} <= candidate_ids)
                self.assertEqual(len({h["candidate_id"] for h in method}), len(method))
                self.assertTrue(all(h["eligible"] and h["representation"] == "original" for h in method))
            blind_order = [mapping[c["clip_id"]]["candidate_id"] for c in q["clips"]]
            raw_order = [h["candidate_id"] for h in predictions["queries"][q["id"]]["raw_semantic"]]
            self.assertNotEqual(blind_order, raw_order)

    def test_empty_future_labels_cannot_produce_metrics(self):
        session = json.loads((ROOT / "prepared/session.json").read_text())
        payload = dict(package_id=session["package_id"], judgments=[])
        self.assertEqual(validate_labels(payload, session), payload)
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "empty-labels.json"
            labels.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "HUMAN AUDITION REQUIRED"):
                calculate(ROOT, labels)
        with self.assertRaises(ValueError):
            validate_labels(dict(package_id="wrong", judgments=[]), session)

    def test_server_serves_only_blinded_surface_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "labels.json"
            server = make_server(ROOT, labels, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(url+"/session") as response:
                    session = json.load(response)
                self.assertFalse(labels.exists())
                clip = session["queries"][0]["clips"][0]
                req = urllib.request.Request(url+"/clip/"+clip["clip_id"], headers={"Range":"bytes=0-63"})
                with urllib.request.urlopen(req) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(len(response.read()), 64)
                with self.assertRaises(urllib.error.HTTPError) as exc:
                    urllib.request.urlopen(url+"/prepared/predictions.json")
                self.assertEqual(exc.exception.code, 404)
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(urllib.request.Request(url+"/labels", data=b"{}", method="POST"))
                self.assertFalse(labels.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
