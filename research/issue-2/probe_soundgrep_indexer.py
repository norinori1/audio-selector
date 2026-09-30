"""Exercise the upstream indexer/DB contract on one fixture, without repairs."""
import argparse
import asyncio
import json
from pathlib import Path

from run_upstream import isolated_module


async def probe(args):
    root = args.repo / "soundgrep"
    dbmod = isolated_module("probe_db", root / "db/schema.py")
    vecmod = isolated_module("probe_vectors", root / "db/vector.py")
    embmod = isolated_module("probe_embeddings", root / "intelligence/audio_embeddings.py")
    analysismod = isolated_module("probe_analysis", root / "intelligence/audio_analysis.py")
    idxmod = isolated_module("probe_indexer", root / "intelligence/sample_indexer.py")
    db = dbmod.DatabaseManager(str(args.out / "probe.sqlite3"))
    await db.init_db()
    report = {}
    try:
        try:
            await db._conn()  # Same call as the upstream CLI, intentionally unmodified.
        except AttributeError as exc:
            report["cli_db_call"] = str(exc)
        vector = vecmod.VectorIndex()
        indexer = idxmod.SampleIndexer(db, vector, embmod.AudioEmbedder(), analysismod.AudioAnalyzer())
        report["sample_indexer_file_result"] = await indexer.index_file(str(args.file.resolve()))
        report["vector_count"] = len(vector)
        report["db_has_insert_sample"] = hasattr(db, "insert_sample")
        report["db_has_add_sample"] = hasattr(db, "add_sample")
    finally:
        await db.close()
    (args.out / "probe.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--file", type=Path, default=Path("corpus/issue-2/01.wav"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/issue-2/soundgrep-probe"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    asyncio.run(probe(args))
