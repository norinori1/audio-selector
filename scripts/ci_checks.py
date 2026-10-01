"""Run existing unittest suites, rejecting every unplanned skip or missing smoke."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
REAL_MODEL_SKIPS = {
    "tests.test_retrieval.RetrievalIntegrationTests."
    "test_real_batch_index_restart_query_reindex_gate_and_staleness":
        "set AUDIO_SELECTOR_REAL_MODEL=1 for real CLAP/Qdrant Windows smoke",
    "tests.test_ranking.RankingIntegrationTests."
    "test_real_signals_rank_eligible_pool_and_cli":
        "set AUDIO_SELECTOR_REAL_MODEL=1 for real CLAP/Qdrant ranking smoke",
}


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def run_suite(suite, expected_skips):
    if suite.countTestCases() == 0:
        print("ERROR: empty test discovery", file=sys.stderr)
        return False
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    observed = Counter((test.id(), reason) for test, reason in result.skipped)
    expected = Counter(expected_skips.items())
    print(f"Skip audit: expected={dict(expected)}, observed={dict(observed)}", flush=True)
    if observed != expected:
        print("ERROR: skipped tests differ from the explicit allowlist", file=sys.stderr)
    if result.expectedFailures:
        print("ERROR: unexpected expected-failure tests", file=sys.stderr)
    return result.wasSuccessful() and observed == expected and not result.expectedFailures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fast", "heavy"))
    mode = parser.parse_args().mode
    required_flag = "1" if mode == "heavy" else "0"
    if os.environ.get("AUDIO_SELECTOR_REAL_MODEL", "0") != required_flag:
        parser.error(f"{mode} requires AUDIO_SELECTOR_REAL_MODEL={required_flag}")
    if mode == "fast":
        # Also applies to the CLI subprocesses launched by the existing tests.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    ordinary = unittest.TestLoader().discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    missing = set(REAL_MODEL_SKIPS) - set(test_ids(ordinary))
    if missing:
        print(f"ERROR: real-model tests missing from discovery: {sorted(missing)}", file=sys.stderr)
        return 1
    ordinary_ok = run_suite(ordinary, REAL_MODEL_SKIPS if mode == "fast" else {})
    research = unittest.TestLoader().discover(str(ROOT / "research/issue-2"))
    research_ok = run_suite(research, {})
    for module, args, schema_path in [
        ("manifest", ["--schema"], "docs/implementation/manifest.schema.json"),
        ("ranking", ["schema"], "docs/implementation/ranking-config.schema.json"),
    ]:
        generated = subprocess.check_output(
            [sys.executable, "-m", f"audio_selector.{module}", *args], text=True)
        if json.loads(generated) != json.loads((ROOT / schema_path).read_text(encoding="utf-8")):
            print(f"ERROR: committed schema differs from CLI: {schema_path}", file=sys.stderr)
            return 1
        print(f"Schema matches CLI: {schema_path}", flush=True)
    return 0 if ordinary_ok and research_ok else 1


if __name__ == "__main__":
    sys.exit(main())
