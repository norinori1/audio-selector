"""Real model and real persistent Qdrant integration; no replacement embeddings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import numpy as np
import librosa
import soundfile as sf

from audio_selector.manifest import Manifest, Policy, sha256
from audio_selector.retrieval import (ClapEmbedder, CONTRACT, LocalIndex, StaleIndexError,
                                      COLLECTION, audio_segments, segment_specs)
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
    def check_segments(self, frames, rate=48000, metadata_frames=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.wav"
            wave = np.full((frames, 2), 0.125, dtype=np.float32)
            sf.write(path, wave, rate, subtype="FLOAT")
            decoded, sr = sf.read(path, dtype="float32", always_2d=True)
            actual = decoded.mean(axis=1)
            if sr != 48000:
                actual = librosa.resample(actual, orig_sr=sr, target_sr=48000, res_type="soxr_hq")
            info = SimpleNamespace(frames=metadata_frames if metadata_frames is not None else frames,
                                   samplerate=rate)
            with patch("audio_selector.retrieval.sf.info", return_value=info):
                self.assertEqual(sf.info(path).frames, info.frames)
                arrays = audio_segments(path)
                specs = segment_specs(path)
            expected_specs = [(start, min(start + 480000, len(actual)))
                              for start in range(0, len(actual), 480000)]
            self.assertTrue(all(a.shape == (480000,) for a in arrays))
            self.assertEqual(specs, expected_specs)
            self.assertEqual(len(arrays), len(expected_specs))
            for (start, end), array in zip(specs, arrays, strict=True):
                np.testing.assert_array_equal(array[:end - start], actual[start:end])
                self.assertTrue(np.all(array[end - start:] == 0))
            self.assertEqual(len(arrays[-1]), 480000)

    def test_metadata_decode_mismatch_resampled_tail(self):
        # Same 3290-frame overestimate observed in #19, with a small local fixture.
        self.check_segments(44100 * 11, 44100, metadata_frames=44100 * 11 + 3290)

    def test_metadata_mismatch_across_segment_boundary(self):
        for metadata_frames in [480000 - 1, 960001]:
            with self.subTest(metadata_frames=metadata_frames):
                # An underestimate must not drop audio; an overestimate must not
                # create an empty segment, including at an exact actual boundary.
                self.check_segments(960000, metadata_frames=metadata_frames)

    def test_non_multiple_tail(self):
        self.check_segments(480000 + 123)

    def test_exact_multiple_without_empty_segment(self):
        for frames in [480000, 960000]:
            with self.subTest(frames=frames):
                self.check_segments(frames)

    def test_short_audio(self):
        self.check_segments(16000, 16000)

    def test_empty_decode_is_rejected_despite_nonempty_metadata(self):
        with patch("audio_selector.retrieval.sf.info", return_value=SimpleNamespace(frames=48000, samplerate=48000)), \
             patch("audio_selector.retrieval.sf.read", return_value=(np.empty((0, 1), dtype=np.float32), 48000)):
            for function in [audio_segments, segment_specs]:
                with self.subTest(function=function.__name__), self.assertRaises(ValueError):
                    function(Path("empty.mp3"))

    def test_clap_fixed_length_validation_is_preserved(self):
        embedder = ClapEmbedder.__new__(ClapEmbedder)
        for size in [0, 476419, 479999, 480001]:
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "exactly 480000 samples"):
                embedder.embed_audio([np.zeros(size, dtype=np.float32)])

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

    def test_metadata_mismatch_persistent_build_reload_and_failed_rebuild(self):
        path = self.root / "drone.wav"
        frames = 48000 * 81 + 123
        t = np.arange(frames) / 48000
        sf.write(path, (0.15 * np.sin(2 * np.pi * 110 * t)).astype("float32"), 48000)
        candidate = self.data["candidates"][1]
        candidate["original"].update(sha256=sha256(path), size=path.stat().st_size)
        self.data["evidence"][0]["asset_sha256s"].append(sha256(path))
        m = self.manifest()
        with patch("audio_selector.retrieval.sf.info", return_value=SimpleNamespace(
                frames=frames + 480000, samplerate=48000)):
            built = self.index.build(m, self.root)
            self.assertEqual(built["vectors"], 10)  # One beep + nine actual drone segments.
            self.assertTrue(self.index.marker.exists())
            expected = self.index.expected(m, self.root, Policy())
            points, _ = self.index.client.scroll(COLLECTION, limit=100, with_payload=True, with_vectors=True)
            payloads = {str(p.id): p.payload for p in points}
            self.assertEqual(payloads, expected)
            stored = {str(p.id): p.vector for p in points}
            self.assertTrue(all(np.isfinite(v).all() for v in stored.values()))
            np.testing.assert_allclose([np.linalg.norm(v) for v in stored.values()], 1, atol=1e-5)
            drone = sorted((p for p in points if p.payload["candidate_id"] == "drone"),
                           key=lambda p: p.payload["segment_start"])
            self.assertEqual([p.payload["segment_start"] for p in drone], list(range(0, 81, 10)))
            self.assertEqual(drone[-1].payload["segment_end"], frames / 48000)
            self.assertEqual(str(drone[-1].id), str(uuid.uuid5(uuid.NAMESPACE_URL,
                f"drone:{candidate['original']['sha256']}:{48000 * 80}")))
            self.index.close()
            self.index = LocalIndex(self.index_path, self.embedder)
            self.assertEqual(self.index.inspect(m, self.root), dict(valid=list(expected), stale=[], missing=[]))
            # Qdrant scroll order is not contractual; compare the ID sets instead.
            points, _ = self.index.client.scroll(COLLECTION, limit=100, with_payload=True, with_vectors=True)
            self.assertEqual({str(p.id) for p in points}, set(stored))
            for point in points:
                # Qdrant 1.12.1 normalizes into float32 memory on upsert but
                # reloads persisted input vectors as float64. Bound that
                # storage rounding by one float32 epsilon, with no relative slack.
                np.testing.assert_allclose(point.vector, stored[str(point.id)],
                                           rtol=0, atol=np.finfo(np.float32).eps)
            hits = self.index.query(m, self.root, "a low steady drone", k=2)
            self.assertEqual(len(hits), 2)
            self.assertTrue(all(h["vector_id"] in expected for h in hits))
            # Simulate the old header-estimated tail payload under the same
            # contract/ID. A marker must not make that inconsistent index valid.
            self.index.client.set_payload(COLLECTION, payload={"segment_end": frames / 48000 + 10},
                                          points=[drone[-1].id])
            with self.assertRaises(StaleIndexError):
                self.index.query(m, self.root, "drone")
            self.assertEqual(self.index.build(m, self.root)["vectors"], 10)
            original_upsert = self.index._upsert
            calls = 0

            def fail_second_batch(keys, arrays, expected):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("injected inference failure after persisted first batch")
                return original_upsert(keys, arrays, expected)

            with patch.object(self.index, "_upsert", side_effect=fail_second_batch):
                with self.assertRaisesRegex(RuntimeError, "injected inference failure"):
                    self.index.build(m, self.root)
            self.assertEqual(self.index.client.count(COLLECTION, exact=True).count, 8)
            self.assertFalse(self.index.marker.exists())
            with self.assertRaises(StaleIndexError):
                self.index.query(m, self.root, "drone")
            self.index.close()
            self.index = LocalIndex(self.index_path, self.embedder)
            with self.assertRaises(StaleIndexError):
                self.index.query(m, self.root, "drone")
            self.assertEqual(self.index.build(m, self.root)["vectors"], 10)
            self.assertEqual(len(self.index.query(m, self.root, "drone", k=2)), 2)

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
