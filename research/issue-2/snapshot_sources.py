"""Record public upstream identity/activity/license metadata without credentials."""
import argparse
import json
from pathlib import Path
import subprocess

REPOS = {
    "semantic-audio-search": "TaaroBravo/semantic-audio-search",
    "soundgrep": "fnsmdehip/soundgrep",
    "laion-clap": "LAION-AI/CLAP",
    "ms-clap": "microsoft/CLAP",
    "pam": "soham97/PAM",
    "dcase2023": "xieh97/dcase2023-audio-retrieval",
    "dcase2025": "CPJKU/dcase2025_task6_baseline",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clones", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for folder, repo in REPOS.items():
        path = args.clones / folder
        metadata = json.loads(subprocess.check_output(["gh", "api", "repos/" + repo], text=True, encoding="utf-8"))
        sha = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        date = subprocess.check_output(["git", "-C", str(path), "show", "-s", "--format=%cI", "HEAD"], text=True).strip()
        licenses = [p.relative_to(path).as_posix() for p in path.glob("*LICENSE*")]
        records.append(dict(repository=repo, sha=sha, commit_date=date,
                            api_pushed_at=metadata["pushed_at"], archived=metadata["archived"],
                            detected_license=(metadata["license"] or {}).get("spdx_id"),
                            root_license_files=licenses,
                            source="https://api.github.com/repos/" + repo))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(observed_on="2026-09-30", repositories=records), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
