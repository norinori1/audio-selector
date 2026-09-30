"""Export only small, reviewable measurements; never copy weights/audio/caches."""
import json
from pathlib import Path


def export_failure(failure):
    """Keep observed diagnostics separate from causal interpretation in the report."""
    lines = failure["message"].splitlines()
    record = dict(type=failure["type"], summary=lines[0] if lines else "")
    detail = "\n".join(lines[1:]).strip()
    if detail:
        record["detail"] = detail[:1000]
        if len(detail) > 1000:
            record["detail_truncated"] = True
    return record


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
            record["failure"] = export_failure(report["failure"])
        records.append(record)
    evidence = dict(observed_on="2026-09-30", runs=records,
                    soundgrep_indexer_probe=json.loads((root / "soundgrep-probe/probe.json").read_text(encoding="utf-8")),
                    corpus=json.loads(Path("corpus/issue-2/manifest.json").read_text(encoding="utf-8")))
    Path("docs/research/issue-2-results.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
