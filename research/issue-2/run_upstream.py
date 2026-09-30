"""Research harness only: execute upstream embeddings, indexing and retrieval.

No replacement model, similarity function, or search engine. Qdrant's real local
backend replaces the network transport to avoid requiring Docker on Windows.
Upstream source remains unmodified. Output stays under ignored artifacts/.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from unittest.mock import patch

QUERIES = ["A high pitched electronic beep repeated several times",
           "A bright ascending musical chime for a game confirmation",
           "A low harsh buzzer for an error",
           "The sound of white noise hissing",
           "A deep kick drum hitting repeatedly",
           "A rising electronic whoosh",
           "A low steady ominous drone",
           "A quiet interface confirmation without a harsh buzzer"]


def sha(repo):
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def sas(args):
    from qdrant_client import QdrantClient
    from huggingface_hub import snapshot_download
    model_path = snapshot_download("laion/clap-htsat-unfused", revision=args.model_revision,
                                   allow_patterns=["*.json", "*.txt", "*.bin"])
    local = QdrantClient(location=":memory:")
    os.environ.update(LIBRARY_DIR=str(args.corpus.resolve()),
                      DB_PATH=str((args.out / "sas.sqlite3").resolve()),
                      AUTO_TAGS="0", SIM_WEIGHT="1", KW_WEIGHT="0", CLAP_MODEL=model_path)
    spec = importlib.util.spec_from_file_location("upstream_sas", args.repo / "api/main.py")
    module = importlib.util.module_from_spec(spec)
    start = time.perf_counter()
    with patch("qdrant_client.QdrantClient", return_value=local):
        spec.loader.exec_module(module)
    # Keep CPU workload bounded and repeatable; no upstream model changes.
    import torch
    torch.set_num_threads(4)
    module.get_clap()
    setup = time.perf_counter() - start
    start = time.perf_counter()
    indexed = module.reindex_folder()
    index_seconds = time.perf_counter() - start
    count = local.count(module.COLLECTION, exact=True).count
    if count != len(list(args.corpus.glob("*.wav"))):
        raise RuntimeError(f"Expected entire corpus indexed, got {count}; upstream can silently skip files")
    results = []
    for query in QUERIES:
        start = time.perf_counter()
        # Raw results are returned by the same real upstream model + Qdrant.
        raw = local.search(module.COLLECTION, module.embed_text_cached(query).tolist(),
                           limit=count, with_payload=True)
        ranked = module.search(query, limit=3)
        results.append(dict(query=query, seconds=time.perf_counter() - start,
                            upstream_top3=[dict(file=r.filename, score=r.score) for r in ranked],
                            qdrant_top3=[dict(file=r.payload["filename"], score=r.score) for r in raw[:3]]))
    result = dict(setup_seconds=setup, indexing_seconds=index_seconds, indexed=indexed,
                  count=count, queries=results, device="CPU", threads=4,
                  model="laion/clap-htsat-unfused",
                  model_revision=args.model_revision,
                  transport="QdrantClient(location=':memory:'); upstream code unmodified",
                  controls="AUTO_TAGS=0 SIM_WEIGHT=1 KW_WEIGHT=0; opaque filenames")
    local.close()
    module.engine.dispose()
    return result


def soundgrep(args):
    # Separate native OpenMP runtimes; never use KMP_DUPLICATE_LIB_OK.
    for stage in ["embed", "index"]:
        (args.out / "stage-error.json").unlink(missing_ok=True)
        process = subprocess.run([sys.executable, __file__, "soundgrep", "--repo", str(args.repo),
                                  "--corpus", str(args.corpus), "--out", str(args.out),
                                  "--stage", stage], capture_output=True)
        if process.returncode:
            failure_path = args.out / "stage-error.json"
            if failure_path.exists():
                failure = json.loads(failure_path.read_text(encoding="utf-8"))
                raise RuntimeError(failure["type"] + ": " + failure["summary"])
            raise RuntimeError(f"Upstream {stage} process exited {process.returncode}: "
                               + process.stderr.decode("utf-8", errors="replace")[-2000:])
    return json.loads((args.out / "stage-result.json").read_text(encoding="utf-8"))


def isolated_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def soundgrep_stage(args):
    import numpy as np
    files = sorted(args.corpus.glob("*.wav"))
    if args.stage == "embed":
        module = isolated_module("upstream_soundgrep_embeddings",
                                 args.repo / "soundgrep/intelligence/audio_embeddings.py")
        if "torch" in sys.modules:
            sys.modules["torch"].set_num_threads(4)
        embedder = module.AudioEmbedder(device="cpu")
        start = time.perf_counter()
        embeddings = embedder.embed_audio_batch([str(p.resolve()) for p in files])
        texts = embedder.embed_text_batch(QUERIES)
        reference = embedder.embed_audio(str(files[1]))
        np.savez(args.out / "vectors.npz", audio=embeddings, text=texts, reference=reference)
        (args.out / "backend.json").write_text(json.dumps(dict(
            backend="laion-clap" if embedder._use_clap else "spectral + random text (INVALID semantic baseline)",
            embedding_seconds=time.perf_counter() - start)), encoding="utf-8")
        return
    module = isolated_module("upstream_soundgrep_vector", args.repo / "soundgrep/db/vector.py")
    index = module.VectorIndex()
    vectors = np.load(args.out / "vectors.npz")
    start = time.perf_counter()
    index.add_batch(vectors["audio"], list(range(len(files))))
    index_seconds = time.perf_counter() - start
    results = []
    for query, embedding in zip(QUERIES, vectors["text"]):
        hits = index.search(embedding, k=3)
        results.append(dict(query=query, top3=[dict(file=files[i].name, score=s) for i, s in hits]))
    audio_hits = index.search(vectors["reference"], k=3)
    result = dict(indexing_seconds=index_seconds, count=len(index),
                **json.loads((args.out / "backend.json").read_text(encoding="utf-8")),
                queries=results, audio_query=files[1].name,
                audio_top3=[dict(file=files[i].name, score=s) for i, s in audio_hits],
                boundary="Isolated upstream AudioEmbedder + VectorIndex in separate processes; not CLI/API or integrated indexer")
    (args.out / "stage-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", choices=["sas", "soundgrep"])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path("corpus/issue-2"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-revision", default="8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a")
    parser.add_argument("--stage", choices=["embed", "index"])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage:
        try:
            soundgrep_stage(args)
        except Exception as exc:
            failure = dict(type=type(exc).__name__, summary=str(exc).splitlines()[0])
            (args.out / "stage-error.json").write_text(json.dumps(failure), encoding="utf-8")
            print(json.dumps(failure))
            raise SystemExit(1)
        return
    report = dict(candidate=args.candidate, upstream_sha=sha(args.repo),
                  python=platform.python_version(), platform=platform.platform(),
                  queries=QUERIES)
    start = time.perf_counter()
    try:
        report["result"] = (sas if args.candidate == "sas" else soundgrep)(args)
    except Exception as exc:
        import traceback
        report["failure"] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    report["total_seconds"] = time.perf_counter() - start
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(candidate=args.candidate, success="result" in report,
                          output=str(args.out / "result.json"),
                          total_seconds=report["total_seconds"])))
    if "failure" in report:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
