"""Prepare blinded complete-corpus judgments and real retrieval comparison sets."""
import argparse
import json
from pathlib import Path

import soundfile as sf
from qdrant_client import models

from .manifest import eligible_candidates, load, sha256
from .retrieval import ClapEmbedder, COLLECTION, LocalIndex, fingerprint


def prepare(root: Path):
    manifest = load(root / "manifest.json")
    eligible = eligible_candidates(manifest, root)
    if len(eligible) != len(manifest.candidates) or not eligible:
        raise ValueError("benchmark requires a nonempty, entirely eligible exact corpus")
    queries = json.loads((root / "queries.json").read_text())
    durations = {c.id: sf.info(root / c.original.path).duration for c in eligible}
    package_id = fingerprint(dict(manifest=manifest.model_dump(mode="json"), queries=queries,
                                  protocol="full-corpus-blind/v1"))
    embedder = ClapEmbedder()
    index = LocalIndex(Path("qdrant_storage/benchmark"), embedder)
    predictions, mapping, public_queries = {}, {}, []
    try:
        built = index.build(manifest, root)
        for q in queries:
            # Full rankings retained privately for K=1/3/5 and exhaustive labels.
            raw = index.query(manifest, root, q["prompt"], k=len(eligible))
            bounded_ids = [cid for cid, seconds in durations.items()
                           if q.get("min_seconds", 0) <= seconds <= q.get("max_seconds", float("inf"))]
            constrained = index.query(manifest, root, q["prompt"], k=len(eligible), candidate_ids=bounded_ids)
            # First-ten-seconds ablation uses the SAME pinned vectors and Qdrant.
            # index.query above has already enforced/purged current eligibility.
            state = index.inspect(manifest, root)
            hits = index.client.search(COLLECTION, embedder.embed_text([q["prompt"]])[0].tolist(),
                query_filter=models.Filter(must=[models.HasIdCondition(has_id=state["valid"]),
                    models.FieldCondition(key="segment_start", range=models.Range(gte=0, lte=0))]),
                limit=len(eligible), with_payload=True)
            first = [dict(**h.payload, raw_cosine=h.score, vector_id=str(h.id)) for h in hits]
            predictions[q["id"]] = dict(raw_semantic=raw, duration_constraint=constrained, first_segment=first)
            clips = []
            for c in eligible:
                opaque = fingerprint([package_id, q["id"], c.id])[:20]
                mapping[opaque] = dict(candidate_id=c.id, query_id=q["id"], original_sha256=c.original.sha256)
                clips.append(dict(clip_id=opaque, duration=durations[c.id]))
            # Independently randomized stable ordering, independent of model ranking.
            clips.sort(key=lambda clip: fingerprint(["blind-order/v1", q["id"], clip["clip_id"]]))
            public_queries.append(dict(id=q["id"], prompt=q["prompt"], clips=clips))
    finally:
        index.close()
    result = root / "prepared"
    result.mkdir(exist_ok=True)
    (result / "predictions.json").write_text(json.dumps(dict(package_id=package_id,
        build=built, queries=predictions), indent=2), encoding="utf-8")
    (result / "blind-map.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    session = dict(package_id=package_id, protocol="full-corpus-blind/v1", queries=public_queries)
    (result / "session.json").write_text(json.dumps(session, indent=2), encoding="utf-8")
    print(json.dumps(dict(package_id=package_id, assets=len(eligible), vectors=built["vectors"],
        queries=len(queries), judgments=len(eligible)*len(queries), labels="outputs/benchmark/labels.json",
        status="HUMAN AUDITION REQUIRED"), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("benchmark"))
    args = parser.parse_args()
    prepare(args.root.resolve())


if __name__ == "__main__":
    main()
