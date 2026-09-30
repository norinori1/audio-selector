"""Pinned CLAP + Qdrant wrappers. No alternative semantic implementation."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

import librosa
import numpy as np
from qdrant_client import QdrantClient, models
import soundfile as sf
import torch
from transformers import ClapModel, ClapProcessor

from .contract import CONTRACT, MODEL, REVISION
from .manifest import Manifest, Policy, eligible_candidates, load

COLLECTION = "audio_selector_v1"


class StaleIndexError(RuntimeError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def candidate_fingerprint(manifest, candidate, policy):
    by_id = {c.id: c for c in manifest.candidates}
    chain = [candidate]
    while chain[-1].parent_id:
        chain.append(by_id[chain[-1].parent_id])
    refs = {ref for c in chain for ref in c.metadata_evidence_ids + c.rights.evidence_ids}
    return fingerprint(dict(candidates=[c.model_dump(mode="json") for c in chain],
        evidence=[e.model_dump(mode="json") for e in manifest.evidence if e.id in refs],
        policy={**policy.model_dump(mode="json"),
                "fulfilled_attribution_ids": sorted(policy.fulfilled_attribution_ids)}))


def segment_specs(path):
    info = sf.info(path)
    if info.frames <= 0:
        raise ValueError("empty audio")
    total = int(np.ceil(info.frames * 48000 / info.samplerate))
    return [(start, min(start + 480000, total)) for start in range(0, total, 480000)]


def audio_segments(path):
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if audio.size == 0 or not np.isfinite(audio).all():
        raise ValueError(f"empty/nonfinite audio: {path}")
    if sr != 48000:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=48000, res_type="soxr_hq")
    return [np.pad(audio[start:end], (0, 480000 - (end - start)))
            for start, end in segment_specs(path)]


class ClapEmbedder:
    contract = CONTRACT

    def __init__(self, *, local_files_only=False):
        # Exceptions propagate. No fake vectors or fallback checkpoint.
        torch.set_num_threads(4)
        self.processor = ClapProcessor.from_pretrained(MODEL, revision=REVISION,
                                                       local_files_only=local_files_only)
        self.model = ClapModel.from_pretrained(MODEL, revision=REVISION,
                                               local_files_only=local_files_only).eval().to("cpu")

    @staticmethod
    def normalize(features):
        if not torch.isfinite(features).all() or torch.any(features.norm(dim=-1) == 0):
            raise ValueError("invalid model output")
        return torch.nn.functional.normalize(features, dim=-1).cpu().numpy()

    def embed_audio(self, arrays, batch_size=8):
        result = []
        for start in range(0, len(arrays), batch_size):
            batch = arrays[start:start + batch_size]
            if any(len(a) != 480000 for a in batch):
                raise ValueError("preprocessed audio must contain exactly 480000 samples")
            inputs = self.processor(audios=batch, sampling_rate=48000, return_tensors="pt")
            with torch.inference_mode():
                result.extend(self.normalize(self.model.get_audio_features(**inputs)))
        return np.asarray(result, dtype=np.float32).reshape(-1, 512)

    def embed_text(self, texts, batch_size=32):
        result = []
        for start in range(0, len(texts), batch_size):
            inputs = self.processor(text=texts[start:start + batch_size], return_tensors="pt",
                                    padding=True, truncation=True, max_length=77)
            with torch.inference_mode():
                result.extend(self.normalize(self.model.get_text_features(**inputs)))
        return np.asarray(result, dtype=np.float32).reshape(-1, 512)

    def embed_files(self, paths, batch_size=8):
        arrays, offsets = [], []
        for path in paths:
            segments = audio_segments(path)
            offsets.append((len(arrays), len(arrays) + len(segments)))
            arrays.extend(segments)
        return self.embed_audio(arrays, batch_size), offsets


class LocalIndex:
    def __init__(self, path: Path, embedder: ClapEmbedder):
        self.path = path
        self.embedder = embedder
        self.client = QdrantClient(path=str(path))
        self.marker = path / "audio-selector-contract.json"

    def close(self):
        self.client.close()

    def expected(self, manifest, root, policy):
        result = {}
        for c in eligible_candidates(manifest, root, policy):
            stamp = candidate_fingerprint(manifest, c, policy)
            for start, end in segment_specs(root / c.original.path):
                key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{c.id}:{c.original.sha256}:{start}"))
                result[key] = dict(candidate_id=c.id, content_sha256=c.original.sha256,
                    representation="original", segment_start=start / 48000,
                    segment_end=end / 48000, candidate_fingerprint=stamp, eligible=True,
                    intended_use=policy.intended_use, policy_version=policy.version,
                    contract=self.embedder.contract)
        return result

    def build(self, manifest: Manifest, root: Path, policy=Policy()):
        expected = self.expected(manifest, root, policy)
        self.marker.unlink(missing_ok=True)
        if self.client.collection_exists(COLLECTION):
            config = self.client.get_collection(COLLECTION).config.params.vectors
            if config.size != 512 or config.distance != models.Distance.COSINE:
                raise StaleIndexError("incompatible Qdrant collection; use a fresh index directory")
            # 1.12.1 local delete_collection leaves SQLite handles open on Windows.
            # Native all-point deletion retains the collection and avoids that defect.
            self.client.delete(COLLECTION, models.FilterSelector(filter=models.Filter()))
        else:
            self.client.create_collection(COLLECTION, vectors_config=models.VectorParams(
                size=512, distance=models.Distance.COSINE))
        arrays, keys = [], []
        for c in eligible_candidates(manifest, root, policy):
            for (start, _), array in zip(segment_specs(root / c.original.path),
                                       audio_segments(root / c.original.path), strict=True):
                keys.append(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{c.id}:{c.original.sha256}:{start}")))
                arrays.append(array)
                # Bound audio memory rather than collecting a library in RAM.
                if len(arrays) == 8:
                    self._upsert(keys, arrays, expected)
                    arrays, keys = [], []
        if arrays:
            self._upsert(keys, arrays, expected)
        # Recheck evidence/content after inference; changes during build fail closed.
        if self.expected(manifest, root, policy) != expected:
            raise StaleIndexError("manifest bytes/evidence changed during build")
        temp = self.marker.with_suffix(".tmp")
        temp.write_text(json.dumps(self.embedder.contract, sort_keys=True), encoding="utf-8")
        temp.replace(self.marker)
        return dict(candidates=len({p["candidate_id"] for p in expected.values()}),
                    vectors=len(expected), contract=self.embedder.contract)

    def _upsert(self, keys, arrays, expected):
        vectors = self.embedder.embed_audio(arrays)
        if vectors.shape != (len(keys), 512) or not np.isfinite(vectors).all():
            raise ValueError("invalid embedding batch")
        self.client.upsert(COLLECTION, points=[models.PointStruct(id=k, vector=v.tolist(),
                           payload=expected[k]) for k, v in zip(keys, vectors, strict=True)])

    def inspect(self, manifest, root, policy=Policy()):
        if not self.marker.exists() or json.loads(self.marker.read_text()) != self.embedder.contract:
            raise StaleIndexError("missing/incompatible build contract; rebuild required")
        expected = self.expected(manifest, root, policy)
        actual, offset = {}, None
        while True:
            points, offset = self.client.scroll(COLLECTION, limit=256, offset=offset,
                                                with_payload=True, with_vectors=False)
            actual.update({str(p.id): p.payload for p in points})
            if offset is None:
                break
        valid = [key for key, payload in expected.items() if actual.get(key) == payload]
        return dict(valid=valid, stale=[key for key in actual if key not in valid],
                    missing=[key for key in expected if key not in valid])

    def vectors(self, manifest, root, candidate_ids, policy=Policy()):
        """Stored segment vectors of currently valid eligible points, in segment order."""
        state = self.inspect(manifest, root, policy)
        if state["missing"]:
            raise StaleIndexError("eligible candidate vectors missing/stale; rebuild required")
        wanted, result = set(candidate_ids), {}
        points = self.client.retrieve(COLLECTION, ids=state["valid"], with_payload=True, with_vectors=True)
        for p in sorted(points, key=lambda p: (p.payload["candidate_id"], p.payload["segment_start"])):
            if p.payload["candidate_id"] in wanted:
                result.setdefault(p.payload["candidate_id"], []).append(p.vector)
        if set(result) != wanted:
            raise StaleIndexError("requested candidates are not valid eligible index records")
        return result

    def query(self, manifest, root, text, k=5, policy=Policy(), candidate_ids=None):
        if k < 1:
            raise ValueError("k must be positive")
        state = self.inspect(manifest, root, policy)
        # Purge derived records for removed/blocked/changed candidates before Top-K.
        if state["stale"]:
            self.client.delete(COLLECTION, models.PointIdsList(points=state["stale"]))
        if state["missing"]:
            raise StaleIndexError("eligible candidate vectors missing/stale; rebuild required")
        if not state["valid"]:
            return []
        conditions = [models.HasIdCondition(has_id=state["valid"]),
            models.FieldCondition(key="eligible", match=models.MatchValue(value=True)),
            models.FieldCondition(key="intended_use", match=models.MatchValue(value=policy.intended_use))]
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            conditions.append(models.FieldCondition(key="candidate_id", match=models.MatchAny(any=candidate_ids)))
        vector = self.embedder.embed_text([text])[0].tolist()
        # Qdrant performs all similarity and filtering. Overfetch segments to return
        # K distinct candidates; each candidate's score is its best segment score.
        hits = self.client.search(COLLECTION, vector, query_filter=models.Filter(must=conditions),
                                  limit=len(state["valid"]), with_payload=True)
        results, seen = [], set()
        for hit in hits:
            if hit.payload["candidate_id"] in seen:
                continue
            seen.add(hit.payload["candidate_id"])
            results.append(dict(**hit.payload, raw_cosine=hit.score, vector_id=str(hit.id)))
            if len(results) == k:
                break
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "query", "inspect"])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--index", type=Path, default=Path("qdrant_storage/default"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--text")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    manifest = load(args.manifest)
    policy = Policy.model_validate_json(args.policy.read_text()) if args.policy else Policy()
    root = args.manifest.resolve().parent
    embedder = ClapEmbedder(local_files_only=args.offline) if args.action != "inspect" else ClapEmbedder.__new__(ClapEmbedder)
    index = LocalIndex(args.index, embedder)
    try:
        if args.action == "build":
            result = index.build(manifest, root, policy)
        elif args.action == "inspect":
            result = index.inspect(manifest, root, policy)
        else:
            if not args.text:
                parser.error("query requires --text")
            result = index.query(manifest, root, args.text, args.k, policy)
        print(json.dumps(result, indent=2))
    finally:
        index.close()


if __name__ == "__main__":
    main()
