"""Issue #7 evaluation integrity: frozen #6 inputs, preregistered binding, reproduction."""
import copy
import hashlib
import itertools
import json
import math
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


class RoleReproductionAssertions(unittest.TestCase):
    # Empirical float64 BLAS rounding allowance on the frozen 512D vectors.
    # No relative tolerance; see docs/ci.md for the scope and measured bound.
    SIMILARITY_ABS_TOL = 1e-15

    def assertRoleMetricsReproduce(self, actual, expected, path=()):
        """Compare JSON types and values, allowing only the two metric diagnostic paths."""
        location = "metrics" + "".join(f".{part}" for part in path)
        self.assertIs(type(actual), type(expected), location)
        if isinstance(expected, dict):
            self.assertEqual(actual.keys(), expected.keys(), location)
            for key in expected:
                self.assertRoleMetricsReproduce(actual[key], expected[key], (*path, key))
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected), location)
            for index, (a, b) in enumerate(zip(actual, expected)):
                self.assertRoleMetricsReproduce(a, b, (*path, index))
        else:
            similarity = (
                len(path) in (4, 6) and path[0] == "results" and path[2] in ("1", "3", "5")
                and ((len(path) == 4 and path[3] == "mean_intra_list_similarity")
                     or (len(path) == 6 and path[3] == "per_query"
                         and type(path[4]) is int and path[5] == "intra_list_similarity")))
            if similarity and isinstance(expected, float):
                self.assertTrue(math.isfinite(actual) and math.isfinite(expected), location)
                self.assertTrue(math.isclose(actual, expected, rel_tol=0,
                                            abs_tol=self.SIMILARITY_ABS_TOL),
                                f"{location}: {actual!r} != {expected!r} "
                                f"(absolute tolerance {self.SIMILARITY_ABS_TOL})")
            else:
                self.assertEqual(actual, expected, location)

    def assertRoleEvaluationReproduces(self, metrics, rankings, expected_metrics, expected_rankings):
        """Check scoped metric rounding and strict ranking JSON, including numeric types."""
        self.assertRoleMetricsReproduce(metrics, expected_metrics)
        self.assertRoleMetricsReproduce(rankings, expected_rankings, path=("rankings",))


class RoleReproductionPolicyTests(RoleReproductionAssertions):
    @classmethod
    def setUpClass(cls):
        """Load the committed metric and ranking references for policy controls."""
        cls.metrics = json.loads((EVAL / "role-metrics-v1.json").read_text())
        cls.rankings = json.loads((EVAL / "role-rankings-v1.json").read_text())

    def assertChangedMetricFails(self, path, value):
        """Require the reproduction gate to reject a replacement at one metric path."""
        changed = copy.deepcopy(self.metrics)
        parent = changed
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = value
        with self.assertRaises(AssertionError):
            self.assertRoleEvaluationReproduces(changed, self.rankings, self.metrics, self.rankings)

    def test_one_ulp_variation_in_both_diagnostics_is_accepted(self):
        """Accept one-ULP perturbations only in the two similarity diagnostics."""
        changed = copy.deepcopy(self.metrics)
        for method in changed["results"].values():
            for result in method.values():
                if result["mean_intra_list_similarity"] is not None:
                    result["mean_intra_list_similarity"] = math.nextafter(
                        result["mean_intra_list_similarity"], math.inf)
                for row in result["per_query"]:
                    if row["intra_list_similarity"] is not None:
                        row["intra_list_similarity"] = math.nextafter(row["intra_list_similarity"], -math.inf)
        self.assertNotEqual(changed, self.metrics)
        self.assertRoleEvaluationReproduces(changed, self.rankings, self.metrics, self.rankings)

    def test_absolute_tolerance_boundary(self):
        """Accept the absolute error limit and reject its next representable float."""
        expected = copy.deepcopy(self.metrics)
        expected["results"]["semantic_only"]["3"]["mean_intra_list_similarity"] = 0.0
        changed = copy.deepcopy(expected)
        result = changed["results"]["semantic_only"]["3"]
        result["mean_intra_list_similarity"] = self.SIMILARITY_ABS_TOL
        self.assertRoleMetricsReproduce(changed, expected)
        result["mean_intra_list_similarity"] = math.nextafter(self.SIMILARITY_ABS_TOL, math.inf)
        with self.assertRaises(AssertionError):
            self.assertRoleMetricsReproduce(changed, expected)

    def test_meaningful_similarity_changes_fail(self):
        """Reject positive and negative diagnostic errors larger than the allowance."""
        for path in [("results", "semantic_only", "3", "mean_intra_list_similarity"),
                     ("results", "semantic_only", "3", "per_query", 0, "intra_list_similarity")]:
            for delta in (-1e-12, 1e-12):
                with self.subTest(path=path, delta=delta):
                    parent = self.metrics
                    for key in path:
                        parent = parent[key]
                    self.assertChangedMetricFails(path, parent + delta)

    def test_other_floating_metrics_remain_exact(self):
        """Reject even one-ULP changes to retrieval and paired/bootstrap metrics."""
        paths = [("results", "semantic_only", "3", key) for key in
                 ("mean_recall", "mAP", "mean_max_pack_share", "projected_time_reduction")]
        paths += [("results", "semantic_only", "3", "per_query", 0, key) for key in ("recall", "ap")]
        paths += [("paired", "semantic_role_vs_semantic_only", "recall@3", "mean_delta"),
                  ("paired", "semantic_role_vs_semantic_only", "recall@3", "bootstrap_95ci", 0)]
        for path in paths:
            with self.subTest(path=path):
                value = self.metrics
                for key in path:
                    value = value[key]
                self.assertChangedMetricFails(path, math.nextafter(value, math.inf))

    def test_null_nonfinite_and_numeric_types_fail_closed(self):
        """Reject null, finite-status and JSON-type changes in the metric reference."""
        row = ("results", "semantic_only", "3", "per_query", 0)
        for value in (None, math.nan, math.inf, -math.inf, True, 0, "0.37"):
            with self.subTest(value=value):
                self.assertChangedMetricFails((*row, "intra_list_similarity"), value)
        self.assertChangedMetricFails(("results", "semantic_only", "1", "mean_intra_list_similarity"), 0.0)
        self.assertChangedMetricFails(("schema_version",), "role-eval-metrics/changed")
        # Python equality considers bool/int/float equal; JSON types must still match.
        self.assertChangedMetricFails((*row, "duplicate_hash_slots"), False)
        self.assertChangedMetricFails(("human_judgments",), float(self.metrics["human_judgments"]))

    def test_identity_config_structure_and_order_remain_exact(self):
        """Reject identity, fingerprint, key-set and list-structure changes."""
        for path in [("package_id",), ("labels_sha256",), ("signals_sha256",),
                     ("ranking_config", "fingerprint"),
                     ("results", "semantic_only", "3", "per_query", 0, "query_id")]:
            with self.subTest(path=path):
                self.assertChangedMetricFails(path, "changed")
        rows = self.metrics["results"]["semantic_only"]["3"]["per_query"]
        row_path = ("results", "semantic_only", "3", "per_query")
        self.assertChangedMetricFails(row_path, rows[::-1])
        self.assertChangedMetricFails(row_path, rows[:-1])
        self.assertChangedMetricFails((*row_path, 0, "shortlist"), rows[0]["shortlist"][::-1])
        for added in (False, True):
            with self.subTest(added=added):
                changed = copy.deepcopy(self.metrics)
                if added:
                    changed["results"]["semantic_only"]["3"]["unexpected"] = 0
                else:
                    del changed["results"]["semantic_only"]["3"]["mean_intra_list_similarity"]
                with self.assertRaises(AssertionError):
                    self.assertRoleEvaluationReproduces(changed, self.rankings, self.metrics, self.rankings)

    def test_similarly_named_fields_outside_allowlist_remain_exact(self):
        """Keep similarity field names exact when they occur outside permitted paths."""
        expected = copy.deepcopy(self.metrics)
        expected["intra_list_similarity"] = 0.5
        changed = copy.deepcopy(expected)
        changed["intra_list_similarity"] = math.nextafter(0.5, math.inf)
        with self.assertRaises(AssertionError):
            self.assertRoleMetricsReproduce(changed, expected)

    def test_rankings_identity_order_and_scores_remain_exact(self):
        """Reject ranking identity, order and one-ULP score changes."""
        for change in ("candidate_id", "sha256", "order", "score"):
            with self.subTest(change=change):
                changed = copy.deepcopy(self.rankings)
                top = changed["q01"]["top_n"]
                if change == "order":
                    top.reverse()
                elif change == "score":
                    top[0]["pre_diversity_score"] = math.nextafter(top[0]["pre_diversity_score"], math.inf)
                else:
                    top[0][change] = "changed"
                with self.assertRaises(AssertionError):
                    self.assertRoleEvaluationReproduces(self.metrics, changed, self.metrics, self.rankings)

    def test_rankings_numeric_types_remain_exact(self):
        """Reject equal-valued int/float/bool substitutions in the ranking JSON."""
        rank_path = ("q01", "top_n", 0, "rank")
        similarity_path = ("q01", "top_n", 0, "reranking", "mmr", "max_similarity_to_prior")
        for path, value in [(rank_path, 1.0), (rank_path, True), (similarity_path, 0)]:
            with self.subTest(path=path, value=value):
                changed = copy.deepcopy(self.rankings)
                parent = changed
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = value
                # These mutations pass Python equality despite changing the JSON type.
                self.assertEqual(changed, self.rankings)
                with self.assertRaises(AssertionError):
                    self.assertRoleEvaluationReproduces(self.metrics, changed, self.metrics, self.rankings)

    def test_rankings_never_use_metric_tolerance(self):
        """Reject ranking rounding even if its keys resemble allowed metric paths."""
        expected = {"results": {"semantic_only": {"3": {"mean_intra_list_similarity": 0.5}}}}
        changed = copy.deepcopy(expected)
        changed["results"]["semantic_only"]["3"]["mean_intra_list_similarity"] = math.nextafter(0.5, math.inf)
        with self.assertRaises(AssertionError):
            self.assertRoleEvaluationReproduces(self.metrics, changed, self.metrics, expected)


class FrozenIssue6Tests(unittest.TestCase):
    def test_human_labels_are_unchanged(self):
        """Verify the published human-label bytes and relevant-judgment counts."""
        meta = json.loads((EVAL / "run-metadata.json").read_text())
        self.assertEqual(hashlib.sha256(LABELS.read_bytes()).hexdigest(), meta["published_labels_sha256"])
        labels = json.loads(LABELS.read_text())["judgments"]
        self.assertEqual((len(labels), sum(j["relevance"] == "relevant" for j in labels)), (156, 36))

    def test_issue6_metrics_reproduce_exactly(self):
        """Recompute Issue #6 metrics exactly against their hashed frozen reference."""
        meta = json.loads((EVAL / "run-metadata.json").read_text())
        self.assertEqual(hashlib.sha256((EVAL / "metrics-v1.json").read_bytes()).hexdigest(), meta["metrics_sha256"])
        self.assertEqual(calculate(BENCH, LABELS), json.loads((EVAL / "metrics-v1.json").read_text()))


class PairedArithmeticTests(unittest.TestCase):
    def test_wins_losses_and_regressions_are_listed(self):
        """Verify paired comparison counts, query lists and bootstrap interval order."""
        def method(values):
            """Construct paired per-query recall/AP inputs for both cutoffs."""
            return {k: dict(per_query=[dict(query_id=q, recall=v, ap=v) for q, v in values.items()])
                    for k in ["3", "5"]}
        results = dict(new=method(dict(q1=1.0, q2=0.0, q3=0.5)), old=method(dict(q1=0.5, q2=0.5, q3=0.5)))
        out = paired(results, "new", "old")["recall@3"]
        self.assertEqual((out["wins"], out["ties"], out["losses"]), (1, 1, 1))
        self.assertEqual((out["improvements"], out["regressions"]), (["q1"], ["q2"]))
        self.assertAlmostEqual(out["mean_delta"], 0)
        self.assertLessEqual(out["bootstrap_95ci"][0], out["bootstrap_95ci"][1])


@unittest.skipUnless(SIGNALS.exists(), "role signals not yet collected")
class RoleEvaluationReproductionTests(RoleReproductionAssertions):
    def test_signals_bound_to_preregistered_config_and_roles(self):
        """Reject config or role assignments changed after frozen signal collection."""
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
        """Reproduce frozen role outputs and the Issue #6 baseline without inference."""
        metrics, rankings = evaluate_all(BENCH, SIGNALS, CONFIG, ROLES, LABELS)
        self.assertRoleEvaluationReproduces(
            json.loads(json.dumps(metrics)), json.loads(json.dumps(rankings)),
            json.loads((EVAL / "role-metrics-v1.json").read_text()),
            json.loads((EVAL / "role-rankings-v1.json").read_text()))
        frozen = json.loads((EVAL / "metrics-v1.json").read_text())["results"]["raw_semantic"]
        for k in ["1", "3", "5"]:
            ours = metrics["results"]["semantic_only"][k]
            self.assertEqual((ours["mean_recall"], ours["mAP"]), (frozen[k]["mean_recall"], frozen[k]["mAP"]))
            self.assertEqual([(r["recall"], r["ap"]) for r in ours["per_query"]],
                             [(r["recall"], r["ap"]) for r in frozen[k]["per_query"]])

    def test_frozen_rankings_respect_invariants(self):
        """Check frozen rankings for eligibility, diversity and score-trace invariants."""
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
