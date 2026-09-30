"""Issue #7 comparison on the frozen Issue #6 corpus and labels.

`collect` runs the pinned CLAP/Qdrant adapter and records signals; it never reads labels.
`evaluate` recomputes every ranking from recorded signals + the preregistered config and
scores it with the Issue #6 metric convention; it never loads the model.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
from statistics import mean
import sys

import numpy as np

from .benchmark_metrics import load_judgments, retrieval_metrics
from .manifest import evaluate as eligibility, load
from .ranking import CandidateSignals, QuerySignals, load_config, rank

KS = (1, 3, 5)
PAIRS = [("semantic_role", "semantic_only"), ("semantic_role_diversity", "semantic_only"),
         ("semantic_role_diversity", "semantic_role")]
BOOTSTRAP = dict(resamples=10000, seed=7)


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root, config_path, roles_path, index_path, *, offline=False):
    from .ranking import collect_signals
    from .retrieval import ClapEmbedder, LocalIndex

    manifest, config = load(root / "manifest.json"), load_config(config_path)
    assignment = json.loads(roles_path.read_text())["queries"]
    queries = json.loads((root / "queries.json").read_text())
    as_of = datetime.now(timezone.utc)
    index = LocalIndex(index_path, ClapEmbedder(local_files_only=offline))
    try:
        index.build(manifest, root)
        signals = {q["id"]: collect_signals(index, manifest, root, q["prompt"],
                                            config.role(assignment[q["id"]]), overfetch=config.overfetch)
                   for q in queries}
    finally:
        index.close()
    vectors = {}
    for s in signals.values():
        for c in s.candidates:
            if vectors.setdefault(c.candidate_id, c.vector) != c.vector:
                raise ValueError("candidate vectors differ between queries")
    predictions = json.loads((root / "prepared/predictions.json").read_text())
    return dict(schema_version="role-eval-signals/1.0", package_id=predictions["package_id"],
        eligibility_as_of=as_of.isoformat(), config_fingerprint=config.fingerprint(),
        query_roles=assignment, vectors=vectors,
        queries={qid: s.model_dump(mode="json", exclude={"candidates": {"__all__": {"vector"}}})
                 for qid, s in signals.items()})


def load_signals(payload):
    result = {}
    for qid, raw in payload["queries"].items():
        candidates = [CandidateSignals(**c, vector=payload["vectors"][c["candidate_id"]])
                      for c in raw["candidates"]]
        result[qid] = QuerySignals(**{**raw, "candidates": candidates})
    return result


def check_baseline(signals, predictions, tolerance=1e-5):
    """Recorded query cosines must reproduce the frozen Issue #6 raw semantic ranking."""
    for qid, s in signals.items():
        frozen = predictions["queries"][qid]["raw_semantic"]
        order = semantic_order(s)
        if order != [h["candidate_id"] for h in frozen]:
            raise ValueError(f"{qid}: semantic baseline order differs from Issue #6 predictions")
        cos = {c.candidate_id: c.query_cosine for c in s.candidates}
        if any(abs(cos[h["candidate_id"]] - h["raw_cosine"]) > tolerance for h in frozen):
            raise ValueError(f"{qid}: semantic cosine differs from Issue #6 predictions")


def semantic_order(signals):
    return [c.candidate_id for c in sorted(signals.candidates, key=lambda c: (-c.query_cosine, c.candidate_id))]


def variants(config):
    """Primary methods plus predeclared exploratory ablations (never used to pick a config)."""
    w, d = config.default_weights, config.diversity
    off = d.model_copy(update=dict(enabled=False))

    def weights(**update):
        return config.model_copy(update=dict(default_weights=w.model_copy(update=update)))
    scaled = lambda f: weights(role_positive=w.role_positive*f, negative=w.negative*f, duration=w.duration*f)
    return {
        "semantic_role": (config, off), "semantic_role_diversity": (config, d),
        "ablation_no_negative": (weights(negative=0), off),
        "ablation_no_role_positive": (weights(role_positive=0), off),
        "ablation_no_duration": (weights(duration=0), off),
        "ablation_duration_only": (weights(role_positive=0, negative=0), off),
        "ablation_role_weights_x0.5": (scaled(0.5), off),
        "ablation_role_weights_x2": (scaled(2), off),
        "ablation_mmr_only_no_caps": (config, d.model_copy(update=dict(
            max_per_lineage=None, max_per_pack=None, max_per_provider=None, near_duplicate_cosine=None))),
        "ablation_caps_only_no_mmr": (config, d.model_copy(update=dict(diversity=0.0))),
        "ablation_mmr_diversity_0.1": (config, d.model_copy(update=dict(diversity=0.1))),
        "ablation_mmr_diversity_0.5": (config, d.model_copy(update=dict(diversity=0.5))),
    }


def diagnostics(ids, signals, pack_key):
    by_id = {c.candidate_id: c for c in signals.candidates}
    items = [by_id[i] for i in ids]
    packs = [getattr(c, pack_key) for c in items]
    sims = [float(np.clip(np.dot(a.vector, b.vector), 0, 1)) for a, b in itertools.combinations(items, 2)]
    return dict(unique_packs=len(set(packs)), unique_providers=len({c.provider for c in items}),
        unique_lineages=len({c.lineage_root for c in items}),
        duplicate_hash_slots=len(items) - len({c.sha256 for c in items}),
        max_pack_share=max(packs.count(p) for p in packs) / len(items) if items else None,
        intra_list_similarity=mean(sims) if sims else None)


def score_method(orderings, signals, judgments, pack_key):
    """orderings: qid -> (shortlist list, full ordering). Issue #6 metric convention."""
    out = {}
    for k in KS:
        rows = []
        for qid, (shortlist, full) in orderings.items():
            pool = {cid: j for (q, cid), j in judgments.items() if q == qid}
            positives = sum(j["relevance"] == "relevant" for j in pool.values())
            ranked = shortlist[:k]
            binary = [int(pool[c]["relevance"] == "relevant") for c in ranked]
            full_seconds = sum(j["audition_seconds"] for j in pool.values())
            short_seconds = sum(pool[c]["audition_seconds"] for c in ranked)
            first = next((i for i, c in enumerate(full, 1) if pool[c]["relevance"] == "relevant"), None)
            rows.append(dict(query_id=qid, positives=positives, **retrieval_metrics(binary, k, positives),
                shortlist=ranked, shortlist_unique_clips=len(ranked), exhaustive_unique_clips=len(pool),
                count_reduction=1 - len(ranked) / len(pool), first_relevant_rank=first,
                projected_time_reduction=1 - short_seconds / full_seconds,
                projected_shortlist_seconds=short_seconds, exhaustive_logged_seconds=full_seconds,
                **diagnostics(ranked, signals[qid], pack_key)))
        valid = [r for r in rows if r["positives"]]
        numeric = lambda key: mean(r[key] for r in rows if r[key] is not None) if any(
            r[key] is not None for r in rows) else None
        out[str(k)] = dict(per_query=rows, mean_recall=mean(r["recall"] for r in valid),
            mAP=mean(r["ap"] for r in valid), zero_positive_queries_excluded=len(rows) - len(valid),
            mean_count_reduction=mean(r["count_reduction"] for r in rows),
            projected_time_reduction=1 - sum(r["projected_shortlist_seconds"] for r in rows) / sum(
                r["exhaustive_logged_seconds"] for r in rows),
            **{f"mean_{key}": numeric(key) for key in ["unique_packs", "unique_providers",
               "unique_lineages", "duplicate_hash_slots", "max_pack_share", "intra_list_similarity",
               "first_relevant_rank"]})
    return out


def paired(results, better, baseline):
    rng = np.random.default_rng(BOOTSTRAP["seed"])
    out = {}
    for k in ["3", "5"]:
        for metric in ["recall", "ap"]:
            a = {r["query_id"]: r[metric] for r in results[better][k]["per_query"]}
            b = {r["query_id"]: r[metric] for r in results[baseline][k]["per_query"]}
            delta = np.array([a[q] - b[q] for q in sorted(a)])
            boot = delta[rng.integers(0, len(delta), (BOOTSTRAP["resamples"], len(delta)))].mean(axis=1)
            out[f"{metric}@{k}"] = dict(mean_delta=float(delta.mean()),
                bootstrap_95ci=[float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
                wins=int((delta > 1e-12).sum()), ties=int((abs(delta) <= 1e-12).sum()),
                losses=int((delta < -1e-12).sum()),
                regressions=[q for q, x in zip(sorted(a), delta) if x < -1e-12],
                improvements=[q for q, x in zip(sorted(a), delta) if x > 1e-12])
    return out


def evaluate_all(root, signals_path, config_path, roles_path, labels_path):
    payload = json.loads(signals_path.read_text())
    config = load_config(config_path)
    if payload["config_fingerprint"] != config.fingerprint():
        raise ValueError("signals were collected for a different ranking config")
    if payload["query_roles"] != json.loads(roles_path.read_text())["queries"]:
        raise ValueError("query/role assignment changed after signal collection")
    signals = load_signals(payload)
    session, predictions, judgments = load_judgments(root, labels_path)
    if payload["package_id"] != session["package_id"]:
        raise ValueError("signals belong to a different benchmark package")
    check_baseline(signals, predictions)
    manifest = load(root / "manifest.json")
    as_of = datetime.fromisoformat(payload["eligibility_as_of"])
    decisions = {c.id: eligibility(manifest, c.id, root, now=as_of) for c in manifest.candidates}
    orderings = {"semantic_only": {q: (semantic_order(s), semantic_order(s)) for q, s in signals.items()}}
    rankings = {}
    for name, (cfg, diversity) in variants(config).items():
        orderings[name] = {}
        for qid, s in signals.items():
            result = rank(s, cfg, decisions, diversity=diversity)
            top = [e["candidate_id"] for e in result["top_n"]]
            orderings[name][qid] = (top, top + [e["candidate_id"] for e in result["beyond_top_n"]])
            if name == "semantic_role_diversity":
                rankings[qid] = result
    results = {name: score_method(o, signals, judgments, config.diversity.pack_key)
               for name, o in orderings.items()}
    frozen = json.loads((root / "evaluation/metrics-v1.json").read_text())["results"]
    return dict(schema_version="role-eval-metrics/1.0", package_id=session["package_id"],
        human_judgments=len(judgments), ranking_config=dict(config_id=config.config_id,
            version=config.version, fingerprint=config.fingerprint()),
        signals_sha256=file_sha256(signals_path), labels_sha256=file_sha256(labels_path),
        eligibility_as_of=payload["eligibility_as_of"], top_n=config.top_n,
        methodology=("Preregistered fixed config; no weights fitted to labels. The same 12 pilot "
            "queries motivated the feature families, so all comparisons are in-sample/exploratory, "
            "not held-out evidence. Ablations are predeclared sensitivity checks, not selection."),
        bootstrap=BOOTSTRAP, issue6_reference={m: {k: dict(mean_recall=v[k]["mean_recall"],
            mAP=v[k]["mAP"]) for k in v} for m, v in frozen.items()},
        results=results, paired={f"{a}_vs_{b}": paired(results, a, b) for a, b in PAIRS}), rankings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["collect", "evaluate"])
    parser.add_argument("--root", type=Path, default=Path("benchmark"))
    parser.add_argument("--config", type=Path, default=Path("benchmark/roles/ranking-v1.json"))
    parser.add_argument("--roles", type=Path, default=Path("benchmark/roles/query-roles-v1.json"))
    parser.add_argument("--signals", type=Path, default=Path("benchmark/evaluation/role-signals-v1.json"))
    parser.add_argument("--labels", type=Path, default=Path("benchmark/evaluation/human-labels-v1.json"))
    parser.add_argument("--index", type=Path, default=Path("qdrant_storage/role-eval"))
    parser.add_argument("--out", type=Path, default=Path("outputs/benchmark/role-metrics.json"))
    parser.add_argument("--rankings-out", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "collect":
            payload = collect(args.root.resolve(), args.config, args.roles, args.index, offline=args.offline)
            args.signals.parent.mkdir(parents=True, exist_ok=True)
            args.signals.write_text(json.dumps(payload, indent=1, allow_nan=False), encoding="utf-8")
            print(f"Signals saved to {args.signals} (labels not read)")
            return
        metrics, rankings = evaluate_all(args.root.resolve(), args.signals, args.config, args.roles, args.labels)
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(metrics, indent=1, allow_nan=False), encoding="utf-8")
    if args.rankings_out:
        args.rankings_out.write_text(json.dumps(rankings, indent=1, allow_nan=False), encoding="utf-8")
    print(f"Role metrics saved to {args.out}")


if __name__ == "__main__":
    main()
