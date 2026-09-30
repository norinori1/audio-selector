"""Real model and real persistent Qdrant integration; no replacement embeddings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audio_selector.manifest import Manifest, sha256
from audio_selector.retrieval import (ClapEmbedder, CONTRACT, LocalIndex, StaleIndexError,
                                      audio_segments)
from tests.test_manifest import fixture


def playable_fixture(root):
    data = fixture(root)
    for name, frequency, duration, rate in [("beep", 1500, 1, 16000), ("drone", 110, 21, 48000)]:
        path = root / f"{name}.wav"
        t = np.arange(int(duration * rate)) / rate
        wave = (0.15 * np.sin(2 * np.pi * frequency * t)).astype("float32")
        sf.write(path, wave, rate)
        candidate = json.loads(json.dumps(data["candidates"][0]))
        candidate.update(id=name, preview=None)
        candidate["original"].update(path=path.name, filename=path.name,
            sha256=sha256(path), size=path.stat().st_size)
        data["evidence"][0]["asset_sha256s"].append(sha256(path))
        data["candidates"].append(candidate)
    data["candidates"] = data["candidates"][1:]
    return data


class PreprocessingTests(unittest.TestCase):
    def test_stereo_resample_tail_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.wav"
            sf.write(path, np.ones((16000 * 11, 2), dtype=np.float32) * 0.1, 16000)
            arrays = audio_segments(path)
            self.assertEqual(len(arrays), 2)
            self.assertTrue(all(a.shape == (480000,) for a in arrays))
            self.assertTrue(np.all(arrays[1][48000:] == 0))

    def test_model_failure_propagates(self):
        with patch("audio_selector.retrieval.ClapProcessor.from_pretrained", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                ClapEmbedder(local_files_only=True)


@unittest.skipUnless(os.environ.get("AUDIO_SELECTOR_REAL_MODEL") == "1",
                     "set AUDIO_SELECTOR_REAL_MODEL=1 for real CLAP/Qdrant Windows smoke")
class RetrievalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.embedder = ClapEmbedder()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = playable_fixture(self.root)
        self.manifest_path = self.root / "manifest.json"
        self.manifest_path.write_text(json.dumps(self.data))
        self.index_path = self.root / "index"
        self.index = LocalIndex(self.index_path, self.embedder)
        self.addCleanup(lambda: self.index.close())

    def manifest(self):
        return Manifest.model_validate(self.data)

    def test_real_batch_index_restart_query_reindex_gate_and_staleness(self):
        m = self.manifest()
        vectors = self.embedder.embed_text(["a high pitched electronic beep", "a low steady drone"])
        self.assertEqual(vectors.shape, (2, 512))
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
        built = self.index.build(m, self.root)
        self.assertEqual(built["vectors"], 4)
        hits = self.index.query(m, self.root, "a high pitched electronic beep", k=2)
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(-1 <= h["raw_cosine"] <= 1 for h in hits))
        self.assertEqual(hits[0]["candidate_id"], "beep")
        self.index.close()
        process = subprocess.run([sys.executable, "-m", "audio_selector.retrieval", "query",
            str(self.manifest_path), "--index", str(self.index_path), "--text",
            "a high pitched electronic beep", "--k", "2", "--offline"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stderr)
        reload_hits = json.loads(process.stdout)
        self.assertEqual([h["candidate_id"] for h in hits], [h["candidate_id"] for h in reload_hits])
        self.index = LocalIndex(self.index_path, self.embedder)
        self.assertEqual(self.index.build(m, self.root)["vectors"], 4)
        self.data["candidates"][0]["rights"]["commercial"] = "denied"
        remaining = self.index.query(self.manifest(), self.root, "a high pitched electronic beep", 2)
        self.assertEqual([h["candidate_id"] for h in remaining], ["drone"])
        for unresolved in ["unknown", None]:
            if unresolved:
                self.data["candidates"][0]["rights"]["commercial"] = unresolved
            else:
                self.data["candidates"][0]["rights"] = None
            self.assertEqual([h["candidate_id"] for h in self.index.query(
                self.manifest(), self.root, "a high pitched electronic beep", 2)], ["drone"])
        self.data["candidates"] = self.data["candidates"][:1]
        self.assertEqual(self.index.query(self.manifest(), self.root, "any sound"), [])
        self.data = playable_fixture(self.root)
        m = self.manifest()
        self.index.build(m, self.root)
        # Same byte length but changed content => eligibility removed immediately.
        path = self.root / "beep.wav"
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        self.assertEqual([h["candidate_id"] for h in self.index.query(m, self.root, "beep")], ["drone"])
        self.data = playable_fixture(self.root)
        self.index.build(self.manifest(), self.root)
        # Still-eligible metadata update requires reindex, rather than stale retrieval.
        self.data["candidates"][0]["author"] = "corrected author"
        with self.assertRaises(StaleIndexError):
            self.index.query(self.manifest(), self.root, "beep")
        self.index.build(self.manifest(), self.root)
        contract = dict(CONTRACT, revision="wrong")
        self.index.marker.write_text(json.dumps(contract))
        with self.assertRaises(StaleIndexError):
            self.index.query(self.manifest(), self.root, "beep")
        self.index.marker.write_text(json.dumps(dict(CONTRACT, preprocessing="wrong")))
        with self.assertRaises(StaleIndexError):
            self.index.query(self.manifest(), self.root, "beep")


if __name__ == "__main__":
    unittest.main()
