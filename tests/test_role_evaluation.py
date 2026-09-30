"""Issue #7 evaluation integrity: frozen #6 inputs, preregistered binding, reproduction."""
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from audio_selector.benchmark_metrics import calculate
from audio_selector.role_evaluation import evaluate_all, paired

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark"
EVAL = BENCH / "evaluation"
SIGNALS = EVAL / "role-signals-v1.json"
CONFIG = BENCH / "roles/ranking-v1.json"
ROLES = BENCH / "roles/query-roles-v1.json"
LABELS = EVAL / "human-labels-v1.json"


class FrozenIssue6Tests(unittest.TestCase):
    def test_human_labels_are_unchanged(self):
        meta = json.loads((EVAL / "run-metadata.json").read_text())
        self.assertEqual(hashlib.sha256(LABELS.read_bytes()).hexdigest(), meta["published_labels_sha256"])
        labels = json.loads(LABELS.read_text())["judgments"]
        self.assertEqual((len(labels), sum(j["relevance"] == "relevant" for j in labels)), (156, 36))

    def test_issue6_metrics_reproduce_exactly(self):
        meta = json.loads((EVAL / "run-metadata.json").read_text())
        self.assertEqual(hashlib.sha256((EVAL / "metrics-v1.json").read_bytes()).hexdigest(), meta["metrics_sha256"])
        self.assertEqual(calculate(BENCH, LABELS), json.loads((EVAL / "metrics-v1.json").read_text()))


class PairedArithmeticTests(unittest.TestCase):
    def test_wins_losses_and_regressions_are_listed(self):
        def method(values):
            return {k: dict(per_query=[dict(query_id=q, recall=v, ap=v) for q, v in values.items()])
                    for k in ["3", "5"]}
        results = dict(new=method(dict(q1=1.0, q2=0.0, q3=0.5)), old=method(dict(q1=0.5, q2=0.5, q3=0.5)))
        out = paired(results, "new", "old")["recall@3"]
        self.assertEqual((out["wins"], out["ties"], out["losses"]), (1, 1, 1))
        self.assertEqual((out["improvements"], out["regressions"]), (["q1"], ["q2"]))
        self.assertAlmostEqual(out["mean_delta"], 0)
        self.assertLessEqual(out["bootstrap_95ci"][0], out["bootstrap_95ci"][1])


@unittest.skipUnless(SIGNALS.exists(), "role signals not yet collected")
class RoleEvaluationReproductionTests(unittest.TestCase):
    def test_signals_bound_to_preregistered_config_and_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = json.loads(CONFIG.read_text())
            changed["default_weights"]["negative"] = 0.4
            path = Path(tmp) / "changed.json"
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "different ranking config"):
                evaluate_all(BENCH, SIGNALS, path, ROLES, LABELS)
            roles = json.loads(ROLES.read_text())
            roles["queries"]["q01"] = "ui-confirm"
            path.write_text(json.dumps(roles))
            with self.assertRaisesRegex(ValueError, "assignment changed"):
                evaluate_all(BENCH, SIGNALS, CONFIG, path, LABELS)

    def test_committed_metrics_and_rankings_reproduce_without_model(self):
        metrics, rankings = evaluate_all(BENCH, SIGNALS, CONFIG, ROLES, LABELS)
        self.assertEqual(json.loads(json.dumps(metrics)), json.loads((EVAL / "role-metrics-v1.json").read_text()))
        self.assertEqual(json.loads(json.dumps(rankings)), json.loads((EVAL / "role-rankings-v1.json").read_text()))
        frozen = json.loads((EVAL / "metrics-v1.json").read_text())["results"]["raw_semantic"]
        for k in ["1", "3", "5"]:
            ours = metrics["results"]["semantic_only"][k]
            self.assertEqual((ours["mean_recall"], ours["mAP"]), (frozen[k]["mean_recall"], frozen[k]["mAP"]))
            self.assertEqual([(r["recall"], r["ap"]) for r in ours["per_query"]],
                             [(r["recall"], r["ap"]) for r in frozen[k]["per_query"]])

    def test_frozen_rankings_respect_invariants(self):
        policy = json.loads(CONFIG.read_text())["diversity"]
        vectors = json.loads(SIGNALS.read_text())["vectors"]
        rankings = json.loads((EVAL / "role-rankings-v1.json").read_text())
        self.assertEqual(len(rankings), 12)
        for result in rankings.values():
            top = result["top_n"]
            self.assertLessEqual(len(top), 5)
            self.assertEqual(len({e["sha256"] for e in top}), len(top))
            for key, cap in [("pack", policy["max_per_pack"]), ("provider", policy["max_per_provider"]),
                             ("lineage_root", policy["max_per_lineage"])]:
                values = [e[key] for e in top]
                self.assertLessEqual(max(values.count(v) for v in values), cap)
            for a, b in itertools.combinations(top, 2):
                similarity = np.dot(vectors[a["candidate_id"]], vectors[b["candidate_id"]])
                self.assertLess(similarity, policy["near_duplicate_cosine"])
            for e in top + result["beyond_top_n"]:
                self.assertEqual(e["eligibility"]["status"], "eligible")
                self.assertAlmostEqual(sum(e["contributions"].values()), e["pre_diversity_score"])
                self.assertEqual(e["reranking"]["decision"] == "deferred",
                                 bool(e["reranking"]["reasons"]) and e["reranking"]["reasons"] != ["beyond top_n"])
