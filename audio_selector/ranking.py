"""Versioned game-role score composition and wrapped MMR diversity reranking.

Eligibility is decided by `manifest.evaluate` and is never an input a score can change.
All text/audio similarity comes from the pinned CLAP/Qdrant adapter; pyversity performs
MMR. This module composes and explains those signals; it is not a similarity engine.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import sys
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, model_validator
import pyversity
from pyversity import Strategy, diversify

from .manifest import Decision, Digest, Model, Policy, Text, evaluate, load

Weight = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Cap = Annotated[int, Field(ge=1)] | None
SCORE_FORMULA = ("pre_diversity = w.query*cos(query) + w.role_positive*mean(cos(positive_i)) "
                 "- w.negative*max(0, max(cos(negative_j)) - cos(query)) - w.duration*(1-duration_fit) "
                 "- sum(dsp weight if outside range) + sum(metadata weight if recorded field matches)")


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Weights(Model):
    query: Weight = 1.0
    role_positive: Weight = 0.5
    negative: Weight = 0.5
    duration: Weight = 0.15


class DurationPreference(Model):
    min_seconds: Annotated[float, Field(gt=0)] | None = None
    max_seconds: Annotated[float, Field(gt=0)] | None = None
    # Soft: fit falls linearly to 0 at this many octaves outside the preferred range.
    tolerance_octaves: Annotated[float, Field(gt=0)] = 1.0
    # Hard: a role constraint (not eligibility); outside candidates are excluded with a reason.
    mode: Literal["soft", "hard"] = "soft"

    @model_validator(mode="after")
    def bounds(self):
        if self.min_seconds is None and self.max_seconds is None:
            raise ValueError("duration preference requires a bound")
        if self.min_seconds and self.max_seconds and self.min_seconds > self.max_seconds:
            raise ValueError("min_seconds exceeds max_seconds")
        return self


class DspCriterion(Model):
    feature: Literal["peak_dbfs", "rms_dbfs", "channels", "sample_rate"]
    min: float | None = None
    max: float | None = None
    weight: Weight


class MetadataCriterion(Model):
    # Only recorded, evidence-backed manifest fields; never free-text inference.
    field: Literal["provider", "author", "kind", "media_type", "acquisition_source"]
    equals: Text
    weight: Annotated[float, Field(allow_inf_nan=False)]


class RoleProfile(Model):
    id: Text
    description: Text
    positive: Annotated[list[Text], Field(min_length=1)]
    # Scored as a separate soft signal. Never an exclusion mechanism.
    negative: list[Text] = []
    duration: DurationPreference | None = None
    dsp: list[DspCriterion] = []
    metadata: list[MetadataCriterion] = []
    weights: Weights | None = None


class DiversityPolicy(Model):
    enabled: bool = True
    algorithm: Literal["pyversity-mmr"] = "pyversity-mmr"
    diversity: Annotated[float, Field(ge=0, le=1)] = 0.25
    pack_key: Literal["acquisition_source", "provider", "author"] = "acquisition_source"
    max_per_lineage: Cap = 1
    max_per_pack: Cap = None
    max_per_provider: Cap = None
    near_duplicate_cosine: Annotated[float, Field(gt=0, le=1)] | None = None


class RankingConfig(Model):
    schema_version: Literal["role-ranking/1.0"] = "role-ranking/1.0"
    config_id: Text
    version: Text
    notes: Text
    top_n: Annotated[int, Field(ge=1)] = 5
    overfetch: Annotated[int, Field(ge=1)] = 50
    default_weights: Weights = Weights()
    diversity: DiversityPolicy = DiversityPolicy()
    roles: Annotated[list[RoleProfile], Field(min_length=1)]

    @model_validator(mode="after")
    def consistent(self):
        if len({r.id for r in self.roles}) != len(self.roles):
            raise ValueError("duplicate role IDs")
        if self.overfetch < self.top_n:
            raise ValueError("overfetch must be at least top_n")
        return self

    def role(self, role_id):
        for role in self.roles:
            if role.id == role_id:
                return role
        raise KeyError(f"unknown role {role_id!r} in {self.config_id} {self.version}")

    def fingerprint(self):
        return canonical_sha256(self.model_dump(mode="json"))


class CandidateSignals(Model):
    candidate_id: Text
    representation: Literal["original"] = "original"
    sha256: Digest
    provider: Text
    author: Text
    kind: Text
    media_type: Text
    acquisition_source: Text
    lineage_root: Text
    query_cosine: float
    best_segment: tuple[float, float]
    positive: dict[str, float]
    negative: dict[str, float]
    dsp: dict[str, float]
    # L2-normalized mean of this candidate's stored segment vectors (diversity only).
    vector: list[float]


class QuerySignals(Model):
    schema_version: Literal["role-signals/1.0"] = "role-signals/1.0"
    query: Text
    role_id: Text
    retrieval_contract: dict
    index_state: Digest
    policy_version: Text
    candidates: list[CandidateSignals]

    @model_validator(mode="after")
    def finite(self):
        for c in self.candidates:
            values = [c.query_cosine, *c.best_segment, *c.positive.values(), *c.negative.values(),
                      *c.dsp.values(), *c.vector]
            if not all(math.isfinite(v) for v in values):
                raise ValueError(f"{c.candidate_id}: nonfinite signal")
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate candidate signals")
        return self


def load_config(path: Path) -> RankingConfig:
    return RankingConfig.model_validate_json(path.read_text(encoding="utf-8"))


def duration_fit(seconds, preference):
    if preference is None:
        return 1.0
    if preference.min_seconds is not None and seconds < preference.min_seconds:
        distance = math.log2(preference.min_seconds / seconds)
    elif preference.max_seconds is not None and seconds > preference.max_seconds:
        distance = math.log2(seconds / preference.max_seconds)
    else:
        return 1.0
    return max(0.0, 1 - distance / preference.tolerance_octaves)


def outside(value, criterion):
    return ((criterion.min is not None and value < criterion.min)
            or (criterion.max is not None and value > criterion.max))


def compose(candidate: CandidateSignals, role: RoleProfile, weights: Weights):
    """Every additive term is returned by name; their sum is the pre-diversity score."""
    if set(candidate.positive) != set(role.positive) or set(candidate.negative) != set(role.negative):
        raise ValueError(f"{candidate.candidate_id}: signals were collected for a different role profile")
    negative = max(candidate.negative.values(), default=None)
    margin = max(0.0, negative - candidate.query_cosine) if negative is not None else 0.0
    fit = duration_fit(candidate.dsp["duration_seconds"], role.duration)
    parts = dict(semantic_query=weights.query * candidate.query_cosine,
        role_positive=weights.role_positive * mean(candidate.positive[t] for t in role.positive),
        negative_penalty=-weights.negative * margin,
        duration=-weights.duration * (1 - fit),
        dsp=-sum(c.weight for c in role.dsp if outside(candidate.dsp[c.feature], c)),
        metadata=sum(c.weight for c in role.metadata if getattr(candidate, c.field) == c.equals))
    detail = dict(duration_fit=fit, negative_max_cosine=negative, negative_margin=margin,
        dsp_outside=[c.feature for c in role.dsp if outside(candidate.dsp[c.feature], c)],
        metadata_matched=[f"{c.field}={c.equals}" for c in role.metadata
                          if getattr(candidate, c.field) == c.equals])
    return parts, detail


def _mmr(items, policy):
    """Order items with pyversity MMR and attach a reproducible explanation per step."""
    vectors = np.asarray([s["c"].vector for s in items], dtype=np.float32)
    relevance = np.asarray([s["score"] for s in items], dtype=np.float32)
    result = diversify(vectors, relevance, k=len(items), strategy=Strategy.MMR,
                       diversity=policy.diversity)
    unit = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), np.finfo(np.float32).eps)
    sims = np.clip(unit @ unit.T, 0.0, 1.0)
    order = [int(i) for i in result.indices]
    for step, (i, gain) in enumerate(zip(order, result.selection_scores)):
        prior = order[:step]
        nearest = max(prior, key=lambda p: (sims[i, p], -p)) if prior else None
        redundancy = float(sims[i, nearest]) if prior else 0.0
        expected = (1 - policy.diversity) * float(relevance[i]) - policy.diversity * redundancy
        # The explanation must reproduce the library's own marginal gain.
        if not math.isclose(expected, float(gain), abs_tol=1e-4):
            raise RuntimeError("MMR explanation does not match pyversity selection score")
        items[i]["mmr"] = dict(step=step + 1, marginal_gain=float(gain),
            relevance_weight=1 - policy.diversity, redundancy_weight=policy.diversity,
            max_similarity_to_prior=redundancy,
            most_similar_prior=items[nearest]["c"].candidate_id if prior else None)
    return [items[i] for i in order], sims


def _violations(item, accepted, policy, sims):
    c, reasons = item["c"], []
    for name, cap, key in [("lineage", policy.max_per_lineage, lambda x: x.lineage_root),
                           ("pack", policy.max_per_pack, lambda x: getattr(x, policy.pack_key)),
                           ("provider", policy.max_per_provider, lambda x: x.provider)]:
        if cap is not None:
            count = sum(key(a["c"]) == key(c) for a in accepted)
            if count >= cap:
                reasons.append(f"{name} cap {cap} reached for {key(c)!r}")
    if policy.near_duplicate_cosine is not None:
        for a in accepted:
            if sims[item["i"], a["i"]] >= policy.near_duplicate_cosine:
                reasons.append(f"near-duplicate of {a['c'].candidate_id} (cosine "
                               f"{sims[item['i'], a['i']]:.4f} >= {policy.near_duplicate_cosine})")
    return reasons


def rank(signals: QuerySignals, config: RankingConfig, decisions: dict[str, Decision], *,
         diversity: DiversityPolicy | None = None, top_n: int | None = None):
    """Deterministic ranking from recorded signals. No model or index access."""
    role = config.role(signals.role_id)
    weights = role.weights or config.default_weights
    policy = config.diversity if diversity is None else diversity
    top_n = top_n or config.top_n
    excluded, suppressed, scored = [], [], []
    for c in signals.candidates:
        decision = decisions.get(c.candidate_id)
        # Fail closed: eligibility is external, current and bound to the exact bytes.
        if decision is None or decision.status != "eligible" or decision.selected_sha256 != c.sha256:
            status = ("missing" if decision is None else decision.status
                      if decision.status != "eligible" else "bound-to-different-bytes")
            reasons = (["no current eligibility decision"] if decision is None else list(decision.reasons)
                       if decision.status != "eligible" else ["decision is for different selected bytes"])
            excluded.append(dict(candidate_id=c.candidate_id, sha256=c.sha256, stage="eligibility",
                                 status=status, reasons=reasons))
            continue
        parts, detail = compose(c, role, weights)
        if role.duration and role.duration.mode == "hard" and detail["duration_fit"] < 1:
            excluded.append(dict(candidate_id=c.candidate_id, sha256=c.sha256, stage="role-constraint",
                status="outside-hard-role-constraint",
                reasons=[f"duration {c.dsp['duration_seconds']:.3f}s outside hard {role.id} bounds"]))
            continue
        scored.append(dict(c=c, decision=decision, parts=parts, detail=detail, score=sum(parts.values())))
    scored.sort(key=lambda s: (-s["score"], s["c"].candidate_id))
    unique, first = [], {}
    for position, s in enumerate(scored, 1):
        s["pre_diversity_rank"] = position
        # Exact bytes are one audition item whatever their IDs/sources. Not configurable.
        if s["c"].sha256 in first:
            s["reasons"] = [f"exact duplicate of {first[s['c'].sha256]} (sha256 {s['c'].sha256})"]
            suppressed.append(s)
        else:
            first[s["c"].sha256] = s["c"].candidate_id
            unique.append(s)
    for i, s in enumerate(unique):
        s["i"] = i
    top, beyond = [], []
    if policy.enabled and unique:
        ordered, sims = _mmr(unique, policy)
        for s in ordered:
            if len(top) < top_n:
                s["reasons"] = _violations(s, top, policy, sims)
                (beyond if s["reasons"] else top).append(s)
                s["decision_label"] = "deferred" if s["reasons"] else "selected"
            else:
                s["reasons"], s["decision_label"] = ["beyond top_n"], "beyond-top-n"
                beyond.append(s)
    else:
        top, beyond = unique[:top_n], unique[top_n:]
        for s in top:
            s["reasons"], s["decision_label"] = [], "selected"
        for s in beyond:
            s["reasons"], s["decision_label"] = ["beyond top_n"], "beyond-top-n"
    for s in suppressed:
        s["decision_label"] = "suppressed"

    def entry(s, position=None):
        c, d = s["c"], s["decision"]
        return dict(rank=position, candidate_id=c.candidate_id, representation=c.representation,
            sha256=c.sha256, provider=c.provider, author=c.author, pack=getattr(c, policy.pack_key),
            lineage_root=c.lineage_root,
            eligibility=dict(status=d.status, intended_use=d.intended_use,
                             policy_version=d.policy_version, reasons=list(d.reasons)),
            signals=dict(query_cosine=c.query_cosine, best_segment=list(c.best_segment),
                         positive=dict(c.positive), negative=dict(c.negative), dsp=dict(c.dsp)),
            contributions=s["parts"], detail=s["detail"], pre_diversity_score=s["score"],
            pre_diversity_rank=s["pre_diversity_rank"],
            reranking=dict(decision=s["decision_label"], reasons=s["reasons"], mmr=s.get("mmr")))

    implementation = None
    if policy.enabled:
        implementation = dict(library="pyversity", version=pyversity.__version__, license="MIT",
            strategy="mmr", reference="Carbonell & Goldstein 1998, SIGIR",
            diversity=policy.diversity, similarity="clipped cosine of candidate centroid vectors")
    return dict(schema_version="role-ranking-result/1.0", query=signals.query, role_id=role.id,
        ranking_config=dict(config_id=config.config_id, version=config.version,
            fingerprint=config.fingerprint(), top_n=top_n, weights=weights.model_dump(),
            diversity=policy.model_dump(), score_formula=SCORE_FORMULA),
        diversity_implementation=implementation, retrieval_contract=signals.retrieval_contract,
        index_state=signals.index_state, eligibility_policy_version=signals.policy_version,
        top_n=[entry(s, i) for i, s in enumerate(top, 1)],
        beyond_top_n=[entry(s, i) for i, s in enumerate(beyond, len(top) + 1)],
        suppressed=[entry(s) for s in suppressed], excluded=excluded)


def lineage_root(manifest, candidate):
    by_id = {c.id: c for c in manifest.candidates}
    while candidate.parent_id:
        candidate = by_id[candidate.parent_id]
    return candidate.id


def collect_signals(index, manifest, root, text, role, *, overfetch, policy=Policy()):
    """Gather every signal from the pinned adapter. Eligibility filtering stays in Qdrant."""
    from .dsp import basic_dsp
    from .retrieval import StaleIndexError

    pool = set()
    # Candidate pool: union of eligible Top-K for the request and each positive description.
    for description in [text, *role.positive]:
        pool.update(h["candidate_id"] for h in index.query(manifest, root, description, overfetch, policy))
    ids = sorted(pool)

    def cosines(description):
        hits = {h["candidate_id"]: h for h in index.query(manifest, root, description, max(1, len(ids)),
                                                          policy, candidate_ids=ids)}
        if set(hits) != set(ids):
            raise StaleIndexError("incomplete signal coverage for candidate pool")
        return hits

    request = cosines(text) if ids else {}
    positive = {t: cosines(t) for t in role.positive} if ids else {}
    negative = {t: cosines(t) for t in role.negative} if ids else {}
    vectors = index.vectors(manifest, root, ids, policy) if ids else {}
    by_id = {c.id: c for c in manifest.candidates}
    candidates = []
    for cid in ids:
        c = by_id[cid]
        if request[cid]["content_sha256"] != c.original.sha256:
            raise StaleIndexError(f"{cid}: signal bound to different bytes")
        centroid = np.mean(np.asarray(vectors[cid], dtype=np.float64), axis=0)
        candidates.append(CandidateSignals(candidate_id=cid, sha256=c.original.sha256,
            provider=c.provider, author=c.author, kind=c.kind, media_type=c.original.media_type,
            acquisition_source=c.acquisition_source, lineage_root=lineage_root(manifest, c),
            query_cosine=request[cid]["raw_cosine"],
            best_segment=(request[cid]["segment_start"], request[cid]["segment_end"]),
            positive={t: hits[cid]["raw_cosine"] for t, hits in positive.items()},
            negative={t: hits[cid]["raw_cosine"] for t, hits in negative.items()},
            dsp=basic_dsp(root / c.original.path),
            vector=(centroid / np.linalg.norm(centroid)).tolist()))
    return QuerySignals(query=text, role_id=role.id, retrieval_contract=index.embedder.contract,
                        index_state=canonical_sha256(index.expected(manifest, root, policy)),
                        policy_version=policy.version, candidates=candidates)


def current_decisions(manifest, root, signals, policy=Policy()):
    return {c.candidate_id: evaluate(manifest, c.candidate_id, root, policy) for c in signals.candidates}


def rank_query(index, manifest, root, text, role_id, config, policy=Policy(), *, top_n=None):
    role = config.role(role_id)
    signals = collect_signals(index, manifest, root, text, role, overfetch=config.overfetch, policy=policy)
    # Decisions are recomputed after signal collection; a newly blocked asset is excluded.
    return rank(signals, config, current_decisions(manifest, root, signals, policy), top_n=top_n)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["query", "validate", "schema"])
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("--config", type=Path, default=Path("benchmark/roles/ranking-v1.json"))
    parser.add_argument("--role")
    parser.add_argument("--text")
    parser.add_argument("--index", type=Path, default=Path("qdrant_storage/default"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--top-n", type=int)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.action == "schema":
        print(json.dumps(RankingConfig.model_json_schema(), indent=2))
        return
    try:
        config = load_config(args.config)
        if args.action == "validate":
            print(json.dumps(dict(config_id=config.config_id, version=config.version,
                                  fingerprint=config.fingerprint(), roles=[r.id for r in config.roles])))
            return
        if not (args.manifest and args.role and args.text):
            parser.error("query requires manifest, --role and --text")
        from .retrieval import ClapEmbedder, LocalIndex
        manifest = load(args.manifest)
        policy = Policy.model_validate_json(args.policy.read_text()) if args.policy else Policy()
        index = LocalIndex(args.index, ClapEmbedder(local_files_only=args.offline))
        try:
            result = rank_query(index, manifest, args.manifest.resolve().parent, args.text, args.role,
                                config, policy, top_n=args.top_n)
        finally:
            index.close()
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    text = json.dumps(result, indent=2, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
