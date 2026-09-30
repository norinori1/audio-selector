"""Evaluate future complete human labels; refuses incomplete/unsure judgments."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean
import sys

from sklearn.metrics import average_precision_score

from .audition import validate_labels


def retrieval_metrics(relevance, k, positives_total):
    """Truncated AP normalized by all positives R, not only observed Top-K hits."""
    y = relevance[:k]
    found = sum(y)
    if positives_total == 0:
        return dict(recall=None, ap=None)
    ap = (float(average_precision_score(y, list(range(len(y), 0, -1)))) * found / positives_total
          if found else 0.0)
    return dict(recall=found/positives_total, ap=ap)


def load_judgments(root, labels_path):
    """Complete decided labels keyed by (query ID, candidate ID) via the frozen blind map."""
    session = json.loads((root / "prepared/session.json").read_text())
    predictions = json.loads((root / "prepared/predictions.json").read_text())
    mapping = json.loads((root / "prepared/blind-map.json").read_text())
    labels = validate_labels(json.loads(labels_path.read_text()), session)
    if predictions["package_id"] != session["package_id"]:
        raise ValueError("prediction package mismatch")
    expected = {(q["id"], c["clip_id"]) for q in session["queries"] for c in q["clips"]}
    actual = {(j["query_id"], j["clip_id"]) for j in labels["judgments"]}
    if actual != expected or any(j["relevance"] == "unsure" for j in labels["judgments"]):
        raise ValueError(f"HUMAN AUDITION REQUIRED: need {len(expected)} complete decided judgments; "
                         f"have {len(actual)} (unsure is not negative)")
    judgments = {(j["query_id"], mapping[j["clip_id"]]["candidate_id"]): j for j in labels["judgments"]}
    return session, predictions, judgments


def calculate(root, labels_path, ks=(1, 3, 5), effort_path=None):
    session, predictions, judgments = load_judgments(root, labels_path)
    output = dict(package_id=session["package_id"], human_judgments=len(judgments), results={})
    for method in ["raw_semantic", "duration_constraint", "first_segment"]:
        output["results"][method] = {}
        for k in ks:
            if k < 1:
                raise ValueError("K must be positive")
            rows = []
            for q in session["queries"]:
                qid = q["id"]
                pool = [j for (query, _), j in judgments.items() if query == qid]
                positives = sum(j["relevance"] == "relevant" for j in pool)
                ranked = predictions["queries"][qid][method][:k]
                binary = [int(judgments[qid, h["candidate_id"]]["relevance"] == "relevant") for h in ranked]
                values = retrieval_metrics(binary, k, positives)
                full_seconds = sum(j["audition_seconds"] for j in pool)
                shortlist_seconds = sum(judgments[qid, h["candidate_id"]]["audition_seconds"] for h in ranked)
                rows.append(dict(query_id=qid, positives=positives, **values,
                    exhaustive_unique_clips=len(pool), shortlist_unique_clips=len(ranked),
                    count_reduction=1-len(ranked)/len(pool),
                    projected_time_reduction=1-shortlist_seconds/full_seconds,
                    exhaustive_logged_seconds=full_seconds,
                    projected_shortlist_seconds=shortlist_seconds))
            valid = [r for r in rows if r["positives"]]
            output["results"][method][str(k)] = dict(per_query=rows,
                mean_recall=mean(r["recall"] for r in valid) if valid else None,
                mAP=mean(r["ap"] for r in valid) if valid else None,
                zero_positive_queries_excluded=len(rows)-len(valid),
                mean_count_reduction=mean(r["count_reduction"] for r in rows),
                projected_time_reduction=1-sum(r["projected_shortlist_seconds"] for r in rows)/sum(
                    r["exhaustive_logged_seconds"] for r in rows))
    output["effort_interpretation"] = (
        "Counts are unique-candidate shortlist reductions. Time is a counterfactual projection using "
        "actual human per-clip listening logs, not a measured causal benefit. Fatigue/taste stay qualitative.")
    if effort_path:
        by_query = {}
        with effort_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if row["query_id"] not in {q["id"] for q in session["queries"]}:
                    raise ValueError("unknown effort query")
                if row["method"] not in ["exhaustive", "shortlist"]:
                    raise ValueError("effort method must be exhaustive/shortlist")
                key = (row["query_id"], row["method"])
                if key in by_query:
                    raise ValueError("duplicate effort observation")
                count, seconds = int(row["clips_auditioned"]), float(row["seconds"])
                import math
                if count < 0 or not math.isfinite(seconds) or seconds <= 0:
                    raise ValueError("invalid effort observation")
                by_query[key] = (count, seconds)
        required = {(q["id"], m) for q in session["queries"] for m in ["exhaustive", "shortlist"]}
        if set(by_query) != required:
            raise ValueError("paired effort observations required for every query")
        baseline = [v for (_, m), v in by_query.items() if m == "exhaustive"]
        shortlist = [v for (_, m), v in by_query.items() if m == "shortlist"]
        if sum(v[0] for v in baseline) == 0:
            raise ValueError("empty effort baseline")
        output["observed_effort"] = dict(count_reduction=1-sum(v[0] for v in shortlist)/sum(v[0] for v in baseline),
            time_reduction=1-sum(v[1] for v in shortlist)/sum(v[1] for v in baseline),
            interpretation="Descriptive paired human-recorded observations; no causal claim without controlled protocol.")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("benchmark"))
    parser.add_argument("--labels", type=Path, default=Path("outputs/benchmark/labels.json"))
    parser.add_argument("--out", type=Path, default=Path("outputs/benchmark/metrics.json"))
    parser.add_argument("--effort", type=Path)
    args = parser.parse_args()
    try:
        result = calculate(args.root, args.labels, effort_path=args.effort)
    except (ValueError, OSError, KeyError) as exc:
        print(f"HUMAN AUDITION REQUIRED: {exc}", file=sys.stderr)
        sys.exit(2)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Human-label metrics saved to {args.out}")


if __name__ == "__main__":
    main()
