"""Export only small, reviewable measurements; never copy weights/audio/caches."""
import json
from pathlib import Path


def main():
    root = Path("artifacts/issue-2")
    records = []
    for name in ["sas", "sas-pinned", "soundgrep-isolated", "soundgrep-clap", "soundgrep-clap-isolated"]:
        report = json.loads((root / name / "result.json").read_text(encoding="utf-8"))
        record = {k: report[k] for k in ["candidate", "upstream_sha", "python", "platform", "total_seconds"]}
        record["run"] = name
        if "result" in report:
            record["result"] = report["result"]
        else:
            failure = report["failure"]
            record["failure"] = dict(type=failure["type"], summary=failure["message"].splitlines()[0],
                                     detail="HTSAT-base architecture requested; default downloaded checkpoint is HTSAT-tiny; missing keys and size mismatches")
        records.append(record)
    evidence = dict(observed_on="2026-09-30", runs=records,
                    soundgrep_indexer_probe=json.loads((root / "soundgrep-probe/probe.json").read_text(encoding="utf-8")),
                    corpus=json.loads(Path("corpus/issue-2/manifest.json").read_text(encoding="utf-8")))
    Path("docs/research/issue-2-results.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
