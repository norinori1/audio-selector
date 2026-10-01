"""Optional exact-original #19 validation; requires local manifest/audio/model.

No downloads, transcoding, replacement assets, or inferred manifest rights.
Generated reports and the persistent index belong in ignored local directories.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import librosa
import numpy as np
import soundfile as sf

from audio_selector.manifest import Policy, eligible_candidates, load, sha256
from audio_selector.retrieval import COLLECTION, ClapEmbedder, LocalIndex, audio_segments, segment_specs


ORIGINAL_SHA256 = "31f8de24525d6a250dba62f15717e2ad7fd9238c32e402cc2177624dfa3ebf89"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True,
                        help="Dedicated validation index; build replaces its derived points")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest_path, policy_path = args.manifest.resolve(), args.policy.resolve()
    root = manifest_path.parent
    manifest = load(manifest_path)
    policy = Policy.model_validate_json(policy_path.read_text(encoding="utf-8"))
    candidates = eligible_candidates(manifest, root, policy)
    if len(candidates) != 1 or candidates[0].original.sha256 != ORIGINAL_SHA256:
        raise ValueError("requires exactly one eligible exact Diaphanous original")
    path = root / candidates[0].original.path
    if sha256(path) != ORIGINAL_SHA256 or path.stat().st_size != 11383035:
        raise ValueError("original bytes do not match Issue #19")
    decoded, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = decoded.mean(axis=1)
    if sr != 48000:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=48000, res_type="soxr_hq")
    specs, arrays = segment_specs(path), audio_segments(path)
    assert all(len(a) == 480000 for a in arrays)
    assert len(arrays) == len(specs) == 29
    assert specs[-1][1] == len(audio)
    tail_size = specs[-1][1] - specs[-1][0]
    np.testing.assert_array_equal(arrays[-1][:tail_size], audio[specs[-1][0]:])
    assert np.all(arrays[-1][tail_size:] == 0)
    result = dict(source_sha256=sha256(path), metadata_frames=sf.info(path).frames,
                  decoded_frames=len(decoded), sample_rate=sr, resampled_samples=len(audio),
                  segment_count=len(arrays), final_segment_length=len(arrays[-1]),
                  final_spec=specs[-1], final_padding=480000 - tail_size)
    embedder = ClapEmbedder(local_files_only=True)
    index_path = args.index.resolve()
    index = LocalIndex(index_path, embedder)
    try:
        result["build"] = index.build(manifest, root, policy)
        assert result["build"]["vectors"] == 29 and index.marker.exists()
        result["marker"] = json.loads(index.marker.read_text())
        expected = index.expected(manifest, root, policy)
        points, _ = index.client.scroll(COLLECTION, limit=100, with_payload=True, with_vectors=True)
        assert {str(p.id): p.payload for p in points} == expected
        stored = {str(p.id): p.vector for p in points}
        np.testing.assert_allclose([np.linalg.norm(v) for v in stored.values()], 1, atol=1e-5)
        assert all(np.isfinite(v).all() for v in stored.values())
    finally:
        index.close()
    # A new interpreter opens the persisted database and the pinned cached model.
    command = [sys.executable, "-m", "audio_selector.retrieval", "query", str(manifest_path),
               "--index", str(index_path), "--policy", str(policy_path), "--offline",
               "--text", "ambient electronic music", "--k", "1"]
    process = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if process.returncode:
        raise RuntimeError(process.stderr)
    result["separate_process_query"] = json.loads(process.stdout)
    assert len(result["separate_process_query"]) == 1
    assert result["separate_process_query"][0]["vector_id"] in expected
    index = LocalIndex(index_path, embedder)
    try:
        result["reload"] = index.inspect(manifest, root, policy)
        assert not result["reload"]["missing"] and not result["reload"]["stale"]
        points, _ = index.client.scroll(COLLECTION, limit=100, with_payload=True, with_vectors=True)
        assert {str(p.id) for p in points} == set(stored)
        for point in points:
            # Qdrant's float32 in-memory normalization and float64 reload differ
            # only by storage rounding, not segment identity or content.
            np.testing.assert_allclose(point.vector, stored[str(point.id)],
                                       rtol=0, atol=np.finfo(np.float32).eps)
        result["rebuild"] = index.build(manifest, root, policy)
        assert result["rebuild"]["vectors"] == 29 and index.marker.exists()
        points, _ = index.client.scroll(COLLECTION, limit=100, with_payload=True, with_vectors=True)
        assert {str(p.id): p.payload for p in points} == expected
        for point in points:
            np.testing.assert_allclose(point.vector, stored[str(point.id)], rtol=0, atol=1e-7)
        result["rebuilt_query"] = index.query(manifest, root, "ambient electronic music", 1, policy)
        assert result["rebuilt_query"][0]["vector_id"] in expected
    finally:
        index.close()
    result["tool_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result["working_tree_diff"] = subprocess.check_output(["git", "diff", "--stat"], text=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
