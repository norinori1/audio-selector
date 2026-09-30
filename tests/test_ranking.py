"""Issue #7 role composition, eligibility separation and diversity invariants."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from pydantic import ValidationError

from audio_selector.manifest import Decision, Manifest, evaluate
from audio_selector.ranking import (CandidateSignals, DiversityPolicy, QuerySignals, RankingConfig,
                                    compose, duration_fit, load_config, rank)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmark/roles/ranking-v1.json"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
ROLE = dict(id="ui", description="test role", positive=["p1", "p2"], negative=["n1"],
            duration=dict(max_seconds=2))


def config(**diversity):
    return RankingConfig(config_id="test", version="0", notes="unit", top_n=3, overfetch=10,
                         roles=[ROLE], diversity=DiversityPolicy(**diversity))


def unit(*values):
    v = np.zeros(8)
    v[:len(values)] = values
    return (v / np.linalg.norm(v)).tolist()


def cand(cid, q, *, sha=None, provider="prov", pack="pack", root=None, vector=None, neg=0.0,
         pos=(0.0, 0.0), seconds=1.0, **extra):
    return CandidateSignals(candidate_id=cid, sha256=sha or hashlib.sha256(cid.encode()).hexdigest(),
        provider=provider, author="a", kind="original", media_type="audio/wav",
        acquisition_source=pack, lineage_root=root or cid, query_cosine=q, best_segment=(0, seconds),
        positive=dict(p1=pos[0], p2=pos[1]), negative=dict(n1=neg),
        dsp=dict(duration_seconds=seconds, sample_rate=48000, channels=1, peak_dbfs=-3, rms_dbfs=-20),
        vector=vector or unit(*(1 if i == len(cid) % 8 else 0.1 for i in range(8))), **extra)


def signals(*candidates):
    return QuerySignals(query="q", role_id="ui", retrieval_contract={}, index_state="0" * 64,
                        policy_version="commercial-game/1.0", candidates=list(candidates))


def eligible(s, **overrides):
    decisions = {c.candidate_id: Decision(candidate_id=c.candidate_id, intended_use="commercial-game",
        policy_version="commercial-game/1.0", status="eligible", reasons=("ok",), decided_at=NOW,
        selected_sha256=c.sha256) for c in s.candidates}
    decisions.update(overrides)
    return decisions


def top(result):
    return [e["candidate_id"] for e in result["top_n"]]


def everywhere(result):
    return [e["candidate_id"] for key in ["top_n", "beyond_top_n"] for e in result[key]]


class ConfigTests(unittest.TestCase):
    def test_versioned_data_driven_config(self):
        cfg = load_config(CONFIG)
        self.assertEqual((cfg.schema_version, cfg.config_id, cfg.version),
                         ("role-ranking/1.0", "benchmark-game-roles", "1.0.0"))
        self.assertEqual(cfg.fingerprint(), load_config(CONFIG).fingerprint())
        changed = cfg.model_copy(update=dict(default_weights=cfg.default_weights.model_copy(
            update=dict(negative=0.4))))
        self.assertNotEqual(changed.fingerprint(), cfg.fingerprint())
        for role in cfg.roles:
            self.assertTrue(role.positive)
            self.assertTrue(set(role.positive).isdisjoint(role.negative))

    def test_role_duration_bounds_are_issue6_preregistered_bounds(self):
        cfg = load_config(CONFIG)
        assignment = json.loads((ROOT / "benchmark/roles/query-roles-v1.json").read_text())["queries"]
        for q in json.loads((ROOT / "benchmark/queries.json").read_text()):
            duration = cfg.role(assignment[q["id"]]).duration
            self.assertEqual((duration.min_seconds, duration.max_seconds, duration.mode),
                             (q.get("min_seconds"), q.get("max_seconds"), "soft"))

    def test_eligibility_and_unknown_fields_cannot_enter_config(self):
        raw = json.loads(CONFIG.read_text())
        for key, value in [("eligible", True), ("license", "CC0"), ("hard_exclude", ["x"])]:
            with self.assertRaises(ValidationError):
                RankingConfig.model_validate({**raw, key: value})
            with self.assertRaises(ValidationError):
                RankingConfig.model_validate({**raw, "roles": [{**raw["roles"][0], key: value}]})
        with self.assertRaises(ValidationError):
            RankingConfig.model_validate({**raw, "roles": raw["roles"] + raw["roles"][:1]})
        with self.assertRaises(ValidationError):
            RankingConfig.model_validate({**raw, "roles": [{**raw["roles"][0],
                                          "duration": {"min_seconds": 5, "max_seconds": 1}}]})
        with self.assertRaises(ValidationError):
            RankingConfig.model_validate({**raw, "default_weights": {"negative": -1}})


class CompositionTests(unittest.TestCase):
    def test_contributions_are_explicit_and_sum_to_score(self):
        s = signals(cand("a", 0.4, pos=(0.2, 0.4), neg=0.6, seconds=4),
                    cand("b", 0.3, pos=(0.1, 0.1), neg=0.1, seconds=1))
        result = rank(s, config(enabled=False), eligible(s))
        entries = {e["candidate_id"]: e for e in result["top_n"]}
        a = entries["a"]["contributions"]
        self.assertAlmostEqual(a["semantic_query"], 0.4)
        self.assertAlmostEqual(a["role_positive"], 0.5 * 0.3)
        self.assertAlmostEqual(a["negative_penalty"], -0.5 * 0.2)
        self.assertAlmostEqual(a["duration"], -0.15)  # one octave above max -> fit 0
        self.assertEqual(entries["b"]["contributions"]["negative_penalty"], 0)
        for e in entries.values():
            self.assertAlmostEqual(sum(e["contributions"].values()), e["pre_diversity_score"])
        self.assertIn("score_formula", result["ranking_config"])

    def test_duration_fit_is_log_scaled(self):
        role = RankingConfig.model_validate(dict(config_id="t", version="0", notes="n", roles=[
            dict(ROLE, duration=dict(min_seconds=20, tolerance_octaves=2))])).roles[0]
        self.assertEqual(duration_fit(30, role.duration), 1)
        self.assertAlmostEqual(duration_fit(10, role.duration), 0.5)
        self.assertEqual(duration_fit(1, role.duration), 0)
        self.assertEqual(duration_fit(1, None), 1)

    def test_dsp_and_verified_metadata_criteria(self):
        cfg = RankingConfig.model_validate(dict(config_id="t", version="0", notes="n", roles=[dict(ROLE,
            dsp=[dict(feature="peak_dbfs", max=-6, weight=0.2)],
            metadata=[dict(field="provider", equals="trusted", weight=0.05)])]))
        parts, detail = compose(cand("a", 0.1, provider="trusted"), cfg.roles[0], cfg.default_weights)
        self.assertEqual((parts["dsp"], parts["metadata"]), (-0.2, 0.05))
        self.assertEqual((detail["dsp_outside"], detail["metadata_matched"]), (["peak_dbfs"], ["provider=trusted"]))

    def test_negative_description_is_soft_never_exclusion(self):
        s = signals(cand("buzzer", 0.5, neg=0.99), cand("x", 0.1), cand("y", 0.1))
        result = rank(s, config(enabled=False), eligible(s))
        self.assertIn("buzzer", everywhere(result))
        self.assertEqual(result["excluded"], [])
        self.assertLess(result["top_n"][0]["contributions"]["negative_penalty"], 0)

    def test_hard_duration_is_role_constraint_not_eligibility(self):
        cfg = RankingConfig.model_validate(dict(config_id="t", version="0", notes="n", roles=[
            dict(ROLE, duration=dict(max_seconds=2, mode="hard"))]))
        s = signals(cand("long", 0.9, seconds=30), cand("short", 0.1))
        result = rank(s, cfg, eligible(s))
        self.assertEqual(everywhere(result), ["short"])
        self.assertEqual(result["excluded"][0]["stage"], "role-constraint")

    def test_signals_for_other_role_are_rejected(self):
        s = signals(cand("a", 0.1))
        other = RankingConfig.model_validate(dict(config_id="t", version="0", notes="n",
                                                  roles=[dict(ROLE, negative=["different"])]))
        with self.assertRaisesRegex(ValueError, "different role profile"):
            rank(s, other, eligible(s))
        with self.assertRaises(ValidationError):
            signals(cand("a", float("nan")))


class EligibilityTests(unittest.TestCase):
    def test_role_score_cannot_override_eligibility(self):
        s = signals(cand("blocked", 0.99, pos=(1, 1)), cand("review", 0.98, pos=(1, 1)),
                    cand("missing", 0.97), cand("swapped", 0.96), cand("ok", -0.5))
        base = eligible(s)
        decisions = {**base,
            "blocked": base["blocked"].model_copy(update=dict(status="ineligible", reasons=("commercial: denied",))),
            "review": base["review"].model_copy(update=dict(status="review-required", reasons=("unknown",))),
            "swapped": base["swapped"].model_copy(update=dict(selected_sha256="f" * 64))}
        del decisions["missing"]
        for policy in [dict(enabled=False), dict(enabled=True), dict(enabled=True, diversity=0)]:
            result = rank(s, config(**policy), decisions)
            self.assertEqual(everywhere(result), ["ok"])
            self.assertEqual({e["candidate_id"]: e["status"] for e in result["excluded"]},
                             dict(blocked="ineligible", review="review-required", missing="missing",
                                  swapped="bound-to-different-bytes"))
            self.assertTrue(all(e["stage"] == "eligibility" for e in result["excluded"]))

    def test_real_manifest_decision_binds_exact_bytes(self):
        from tests.test_manifest import fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest.model_validate(fixture(root))
            c = manifest.candidates[0]
            s = signals(cand(c.id, 0.5, sha=c.original.sha256))
            self.assertEqual(top(rank(s, config(), {c.id: evaluate(manifest, c.id, root, now=NOW)})), [c.id])
            (root / c.original.path).write_bytes(b"changed bytes")
            result = rank(s, config(), {c.id: evaluate(manifest, c.id, root, now=NOW)})
            self.assertEqual((top(result), result["excluded"][0]["status"]), ([], "review-required"))


class DiversityTests(unittest.TestCase):
    def test_exact_duplicate_hash_never_occupies_two_slots(self):
        same = "a" * 64
        s = signals(cand("src1", 0.9, sha=same), cand("src2", 0.89, sha=same, provider="other"),
                    cand("c", 0.1), cand("d", 0.05))
        for policy in [dict(enabled=False), dict(enabled=True), dict(enabled=True, diversity=1.0,
                       max_per_lineage=None)]:
            result = rank(s, config(**policy), eligible(s), top_n=4)
            ids = everywhere(result)
            self.assertEqual(ids.count("src1") + ids.count("src2"), 1)
            self.assertEqual([e["candidate_id"] for e in result["suppressed"]], ["src2"])
            self.assertIn("exact duplicate of src1", result["suppressed"][0]["reranking"]["reasons"][0])

    def test_group_caps_are_deterministic_and_explained(self):
        s = signals(cand("a1", 0.9, pack="A", root="fam"), cand("a2", 0.85, pack="A", root="fam"),
                    cand("a3", 0.8, pack="A"), cand("a4", 0.75, pack="A"), cand("b1", 0.1, pack="B"))
        result = rank(s, config(max_per_lineage=1, max_per_pack=2, diversity=0), eligible(s))
        self.assertEqual(top(result), ["a1", "a3", "b1"])
        reasons = {e["candidate_id"]: e["reranking"]["reasons"] for e in result["beyond_top_n"]}
        self.assertIn("lineage cap 1 reached for 'fam'", reasons["a2"])
        self.assertIn("pack cap 2 reached for 'A'", reasons["a4"])
        shuffled = signals(*reversed(s.candidates))
        self.assertEqual(json.dumps(result), json.dumps(rank(shuffled, config(max_per_lineage=1,
                         max_per_pack=2, diversity=0), eligible(s))))

    def test_provider_cap_and_near_duplicate_threshold(self):
        v = unit(1, 0, 0)
        s = signals(cand("x", 0.9, vector=v), cand("x-copy", 0.8, vector=unit(1, 0.01, 0)),
                    cand("y", 0.7, provider="p2", vector=unit(0, 1, 0)), cand("z", 0.6, vector=unit(0, 0, 1)))
        result = rank(s, config(near_duplicate_cosine=0.95, max_per_provider=1, diversity=0), eligible(s))
        self.assertEqual(top(result), ["x", "y"])
        reasons = {e["candidate_id"]: " ".join(e["reranking"]["reasons"]) for e in result["beyond_top_n"]}
        self.assertIn("near-duplicate of x", reasons["x-copy"])
        self.assertIn("provider cap 1", reasons["z"])

    def test_mmr_reorders_redundant_items_with_library_trace(self):
        s = signals(cand("a", 0.60, vector=unit(1, 0)), cand("a-like", 0.59, vector=unit(1, 0.05)),
                    cand("b", 0.50, vector=unit(0, 1)))
        plain = rank(s, config(enabled=False), eligible(s))
        diverse = rank(s, config(diversity=0.25, max_per_lineage=None), eligible(s))
        self.assertEqual(top(plain), ["a", "a-like", "b"])
        self.assertEqual(top(diverse), ["a", "b", "a-like"])
        mmr = {e["candidate_id"]: e["reranking"]["mmr"] for e in diverse["top_n"]}
        self.assertEqual(mmr["a"]["step"], 1)
        self.assertEqual(mmr["a-like"]["most_similar_prior"], "a")
        self.assertGreater(mmr["a-like"]["max_similarity_to_prior"], 0.99)
        self.assertEqual(diverse["diversity_implementation"]["library"], "pyversity")
        self.assertIsNone(plain["diversity_implementation"])
        self.assertEqual(json.dumps(diverse), json.dumps(rank(s, config(diversity=0.25,
                         max_per_lineage=None), eligible(s))))

    def test_zero_diversity_without_caps_equals_role_order(self):
        s = signals(*[cand(f"c{i}", 0.1 * i, vector=unit(i + 1, 1)) for i in range(6)])
        a = rank(s, config(enabled=False), eligible(s), top_n=6)
        b = rank(s, config(diversity=0, max_per_lineage=None), eligible(s), top_n=6)
        self.assertEqual(top(a), top(b))


@unittest.skipUnless(os.environ.get("AUDIO_SELECTOR_REAL_MODEL") == "1",
                     "set AUDIO_SELECTOR_REAL_MODEL=1 for real CLAP/Qdrant ranking smoke")
class RankingIntegrationTests(unittest.TestCase):
    def test_real_signals_rank_eligible_pool_and_cli(self):
        from audio_selector.ranking import rank_query
        from audio_selector.retrieval import ClapEmbedder, LocalIndex
        from tests.test_retrieval import playable_fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = playable_fixture(root)
            (root / "manifest.json").write_text(json.dumps(data))
            cfg = RankingConfig.model_validate(dict(config_id="t", version="0", notes="n", top_n=2,
                overfetch=2, roles=[dict(id="beep", description="d", positive=["an electronic beep"],
                negative=["a low drone"], duration=dict(max_seconds=3))]))
            (root / "config.json").write_text(cfg.model_dump_json())
            index = LocalIndex(root / "index", ClapEmbedder(local_files_only=True))
            try:
                manifest = Manifest.model_validate(data)
                index.build(manifest, root)
                result = rank_query(index, manifest, root, "a high pitched beep", "beep", cfg)
                self.assertEqual(top(result), ["beep", "drone"])
                beep = result["top_n"][0]
                self.assertEqual(set(beep["signals"]["positive"]), {"an electronic beep"})
                self.assertEqual(result["retrieval_contract"]["revision"], "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a")
                self.assertLess(result["top_n"][1]["contributions"]["duration"], 0)
                data["candidates"][0]["rights"]["commercial"] = "denied"
                blocked = rank_query(index, Manifest.model_validate(data), root, "a high pitched beep", "beep", cfg)
                self.assertEqual(everywhere(blocked), ["drone"])
                data = playable_fixture(root)
                (root / "manifest.json").write_text(json.dumps(data))
                index.build(Manifest.model_validate(data), root)
            finally:
                index.close()
            process = subprocess.run([sys.executable, "-m", "audio_selector.ranking", "query",
                str(root / "manifest.json"), "--config", str(root / "config.json"), "--role", "beep",
                "--text", "a high pitched beep", "--index", str(root / "index"), "--offline"],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(top(json.loads(process.stdout)), ["beep", "drone"])


if __name__ == "__main__":
    unittest.main()
