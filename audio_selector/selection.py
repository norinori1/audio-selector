"""Human audition decisions bound to exact candidate identity; reproducible export/import.

Ordering is the frozen Issue #7 ranking result, stored verbatim. This module never ranks
and never decides: every decision is a human event. Nothing is accepted automatically.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contract import CONTRACT
from .manifest import Digest, Manifest, Model, Policy, Text, evaluate, sha256 as file_sha256
from .ranking import canonical_sha256

STATE_SCHEMA = "audition-state/1.0"
EXPORT_SCHEMA = "audition-selection-export/1.0"
REPORT_SCHEMA = "audition-import-report/1.0"
RANKING_SCHEMA = "role-ranking-result/1.0"
SELECTING = {"accept", "shortlist", "maybe"}
DecisionValue = Literal["accept", "shortlist", "maybe", "reject"]
Representation = Literal["original", "preview"]


class DecisionEvent(Model):
    # None retracts an earlier decision; history is append-only.
    decision: DecisionValue | None
    note: Annotated[str, Field(max_length=4000)] = ""
    decided_at: datetime
    # Identity, bytes, eligibility and provenance observed when the human decided.
    verification: dict
    provenance: dict | None = None


class CandidateRecord(Model):
    package_id: Digest
    candidate_id: Text
    representation: Representation
    sha256: Digest
    events: Annotated[list[DecisionEvent], Field(min_length=1)]

    def key(self):
        return (self.package_id, self.candidate_id, self.representation, self.sha256)


class Package(Model):
    package_id: Digest
    added_at: datetime
    # Verbatim Issue #7 `role-ranking-result/1.0` output; authoritative ordering.
    ranking: dict

    @model_validator(mode="after")
    def bound(self):
        if self.ranking.get("schema_version") != RANKING_SCHEMA:
            raise ValueError("package must contain an Issue #7 role-ranking-result/1.0")
        if canonical_sha256(self.ranking) != self.package_id:
            raise ValueError("ranking package content does not match its package_id")
        return self


class State(Model):
    schema_version: Literal["audition-state/1.0"] = STATE_SCHEMA
    packages: list[Package] = []
    records: list[CandidateRecord] = []

    @model_validator(mode="after")
    def consistent(self):
        packages = {p.package_id: p for p in self.packages}
        if len(packages) != len(self.packages):
            raise ValueError("duplicate ranking package")
        if len({r.key()[:3] for r in self.records}) != len(self.records):
            raise ValueError("duplicate decision record")
        for r in self.records:
            if r.package_id not in packages:
                raise ValueError(f"{r.candidate_id}: decision refers to unknown ranking package")
            entry = ranked_entry(packages[r.package_id].ranking, r.candidate_id)
            if entry is None or (entry["sha256"], entry["representation"]) != (r.sha256, r.representation):
                raise ValueError(f"{r.candidate_id}: decision identity is not in its ranking package")
        return self


def now_utc():
    return datetime.now(timezone.utc)


def ranked_entry(ranking, candidate_id):
    return next((e for e in ranking["top_n"] + ranking["beyond_top_n"]
                 if e["candidate_id"] == candidate_id), None)


def policy_record(policy: Policy):
    return {**policy.model_dump(mode="json"), "fulfilled_attribution_ids": sorted(policy.fulfilled_attribution_ids)}


def manifest_digest(manifest: Manifest):
    return canonical_sha256(manifest.model_dump(mode="json"))


def inside(root: Path, path: Path):
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def provenance(manifest: Manifest, candidate_id):
    """Manifest record plus every evidence record it references, as recorded now."""
    c = next((c for c in manifest.candidates if c.id == candidate_id), None)
    if c is None:
        return None
    refs = set(c.metadata_evidence_ids + (c.rights.evidence_ids if c.rights else []))
    return dict(candidate=c.model_dump(mode="json"), manifest_sha256=manifest_digest(manifest),
                evidence=[e.model_dump(mode="json") for e in manifest.evidence if e.id in refs])


def verify(manifest: Manifest, root: Path, policy: Policy, candidate_id, representation, expected_sha256,
           *, now=None):
    """Current state of one exact identity. Never looks for an alternative file."""
    now = now or now_utc()
    base = dict(candidate_id=candidate_id, representation=representation, expected_sha256=expected_sha256,
                checked_at=now.isoformat(), manifest_sha256=manifest_digest(manifest))
    c = next((c for c in manifest.candidates if c.id == candidate_id), None)
    if c is None:
        return dict(base, identity="removed-from-manifest", file="unknown", eligibility=None,
                    playable=False, issues=["candidate is no longer in the manifest"])
    blob = c.original if representation == "original" else c.preview
    issues, identity, file_state = [], "ok", "unknown"
    if blob is None:
        identity = "representation-missing"
        issues.append(f"manifest no longer records a {representation} representation")
    elif blob.sha256 != expected_sha256:
        identity = "manifest-records-different-bytes"
        issues.append(f"manifest now records {blob.sha256[:12]}... for this candidate, not {expected_sha256[:12]}...")
    if blob is not None:
        path = root / blob.path
        if not inside(root, path):
            file_state = "outside-manifest-root"
            issues.append("recorded path resolves outside the manifest directory")
        elif not path.is_file():
            file_state = "missing"
            issues.append("local file missing")
        else:
            actual = file_sha256(path)
            file_state = "ok" if actual == expected_sha256 else "hash-changed"
            if actual != expected_sha256:
                issues.append(f"local bytes changed: expected {expected_sha256[:12]}..., found {actual[:12]}...")
    decision = evaluate(manifest, candidate_id, root, policy, representation=representation, now=now)
    if decision.status != "eligible":
        issues.append(f"eligibility now {decision.status}: {'; '.join(decision.reasons)}")
    return dict(base, identity=identity, file=file_state, eligibility=decision.model_dump(mode="json"),
                playable=identity == "ok" and file_state == "ok" and decision.status == "eligible",
                issues=issues)


def verified_bytes(manifest, root, policy, candidate_id, representation, expected_sha256):
    """Exact bytes for playback, read once and hash-checked; otherwise ValueError."""
    status = verify(manifest, root, policy, candidate_id, representation, expected_sha256)
    if not status["playable"]:
        raise ValueError("; ".join(status["issues"]) or "not playable")
    c = next(c for c in manifest.candidates if c.id == candidate_id)
    blob = c.original if representation == "original" else c.preview
    data = (root / blob.path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("bytes changed while reading; refusing to serve")
    return data, blob.media_type


class Store:
    """Single-writer JSON state with atomic replace; survives process restart."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.state = (State.model_validate_json(path.read_text(encoding="utf-8"))
                      if path.exists() else State())

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(self.state.model_dump_json(indent=1), encoding="utf-8")
        temp.replace(self.path)

    def package(self, package_id):
        return next((p for p in self.state.packages if p.package_id == package_id), None)

    def record(self, package_id, candidate_id, representation):
        return next((r for r in self.state.records if r.key()[:3] == (package_id, candidate_id, representation)), None)

    def add_package(self, ranking: dict, *, added_at=None):
        package_id = canonical_sha256(ranking)
        with self.lock:
            if self.package(package_id) is None:
                self.state = State(packages=[*self.state.packages, Package(package_id=package_id,
                    added_at=added_at or now_utc(), ranking=ranking)], records=self.state.records)
                self.save()
        return package_id

    def decide(self, manifest, root, policy, *, package_id, candidate_id, representation, sha256,
               decision, note="", now=None):
        now = now or now_utc()
        with self.lock:
            package = self.package(package_id)
            if package is None:
                raise KeyError("unknown ranking package")
            entry = ranked_entry(package.ranking, candidate_id)
            if entry is None or (entry["sha256"], entry["representation"]) != (sha256, representation):
                raise ValueError("candidate identity is not part of this ranking package")
            status = verify(manifest, root, policy, candidate_id, representation, sha256, now=now)
            # A human cannot select what cannot currently be verified and listened to.
            if decision in SELECTING and not status["playable"]:
                raise ValueError("cannot select an unverified/ineligible candidate: " + "; ".join(status["issues"]))
            event = DecisionEvent(decision=decision, note=note, decided_at=now, verification=status,
                                  provenance=provenance(manifest, candidate_id))
            old = self.record(package_id, candidate_id, representation)
            record = CandidateRecord(package_id=package_id, candidate_id=candidate_id,
                representation=representation, sha256=sha256, events=[*(old.events if old else []), event])
            self.state = State(packages=self.state.packages,
                               records=[r for r in self.state.records if r is not old] + [record])
            self.save()
            return record


def ranking_context(ranking):
    """Selection copy of the frozen ranking's request/config/model/index identity."""
    return dict(query=ranking["query"], role_id=ranking["role_id"],
                ranking_config={k: ranking["ranking_config"][k] for k in ["config_id", "version", "fingerprint"]},
                retrieval_contract=ranking["retrieval_contract"], index_state=ranking["index_state"],
                eligibility_policy_version=ranking["eligibility_policy_version"])


def score_record(entry):
    """Selection copy of the frozen ranking entry's score breakdown."""
    return {k: entry[k] for k in ["pre_diversity_score", "pre_diversity_rank", "contributions",
                                  "detail", "signals", "reranking"]}


def build_export(state: State, manifest: Manifest, root: Path, policy: Policy, *, now=None):
    """Self-contained historical record: frozen rankings, exact identities, decisions, checks."""
    now = now or now_utc()
    packages = {p.package_id: p for p in state.packages}
    selections, used = [], []
    for r in sorted(state.records, key=lambda r: (r.package_id, r.candidate_id)):
        last = r.events[-1]
        if last.decision is None:
            continue
        ranking = packages[r.package_id].ranking
        entry = ranked_entry(ranking, r.candidate_id)
        used.append(r.package_id)
        selections.append(dict(candidate_id=r.candidate_id, representation=r.representation, sha256=r.sha256,
            package_id=r.package_id, rank=entry["rank"], decision=last.decision, note=last.note,
            decided_at=last.decided_at.isoformat(),
            decision_history=[e.model_dump(mode="json") for e in r.events],
            provenance_at_decision=last.provenance,
            eligibility_at_decision=last.verification.get("eligibility"),
            ranking_context=ranking_context(ranking), score=score_record(entry),
            verification_at_export=verify(manifest, root, policy, r.candidate_id, r.representation,
                                          r.sha256, now=now)))
    flagged = [dict(candidate_id=s["candidate_id"], decision=s["decision"],
                    issues=s["verification_at_export"]["issues"])
               for s in selections if s["verification_at_export"]["issues"]]
    export = dict(schema_version=EXPORT_SCHEMA, exported_at=now.isoformat(),
        tool=dict(name="audio-selector", ranking_result_schema=RANKING_SCHEMA),
        manifest_at_export=dict(schema_version=manifest.schema_version, canonical_sha256=manifest_digest(manifest)),
        eligibility_policy=policy_record(policy), retrieval_contract_at_export=CONTRACT,
        packages=[packages[p].model_dump(mode="json") for p in sorted(set(used))],
        selections=selections,
        integrity=dict(all_verified=not flagged,
                       selected_verified=not any(f["decision"] in SELECTING for f in flagged),
                       flagged=flagged))
    export["content_sha256"] = canonical_sha256(export)
    return export


def write_export(export, directory: Path):
    """Exports are immutable historical files: exclusive create, never overwritten."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = export["exported_at"].replace(":", "").replace("-", "").split(".")[0]
    path = directory / f"selection-{stamp}-{export['content_sha256'][:12]}.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(export, indent=1, allow_nan=False))
    return path


def _check(ok, detail):
    return dict(ok=bool(ok), detail=detail)


def _same_instant(value, instant):
    try:
        return datetime.fromisoformat(value) == instant
    except (TypeError, ValueError):
        return False


def duplicate_selections(export):
    keys = [(s.get("package_id"), s.get("candidate_id"), s.get("representation")) for s in export["selections"]]
    return sorted({k[1] for k in keys if keys.count(k) > 1})


def consistency_checks(selection, packages):
    """Duplicated selection fields against their sources: the frozen ranking package and the
    last human event. Independent of content_sha256, so recomputed-hash tampering is caught."""
    s = selection
    package = packages.get(s.get("package_id"))
    entry = ranked_entry(package.ranking, s.get("candidate_id")) if package else None
    try:
        history = [DecisionEvent.model_validate(e) for e in s.get("decision_history") or []]
    except ValueError:
        history = []
    last = history[-1] if history else None
    checks = dict(
        ranking_identity=_check(entry is not None and (entry["sha256"], entry["representation"], entry["rank"])
            == (s.get("sha256"), s.get("representation"), s.get("rank")),
            "candidate, representation, SHA-256 and rank equal the frozen ranking entry"),
        ranking_score=_check(entry is not None and s.get("score") == score_record(entry),
            "score breakdown equals the frozen ranking entry"),
        ranking_context=_check(package is not None and s.get("ranking_context") == ranking_context(package.ranking),
            "request, role, config, model contract, index state and policy version equal the frozen package"),
        decision=_check(last is not None and s.get("decision") in SELECTING | {"reject"}
            and (last.decision, last.note) == (s.get("decision"), s.get("note"))
            and _same_instant(s.get("decided_at"), last.decided_at),
            "decision, note and decided_at equal the last valid recorded human event"),
        decision_snapshot=_check(last is not None and s.get("provenance_at_decision") == last.provenance
            and s.get("eligibility_at_decision") == last.verification.get("eligibility"),
            "provenance and eligibility snapshots equal those stored on the last human event"))
    return checks, package, history


def verify_export(export: dict, manifest: Manifest, root: Path, policy: Policy, *, config_fingerprint=None,
                  now=None):
    """Explicit comparison of an export against its frozen packages and current bytes/evidence/policy/model/config."""
    issues = []
    if export.get("schema_version") != EXPORT_SCHEMA:
        raise ValueError(f"not an {EXPORT_SCHEMA} document")
    body = {k: v for k, v in export.items() if k != "content_sha256"}
    if canonical_sha256(body) != export.get("content_sha256"):
        issues.append("content_sha256 mismatch: export was edited or corrupted")
    packages = {}
    for raw in export["packages"]:
        try:
            p = Package.model_validate(raw)
            packages[p.package_id] = p
        except ValueError as exc:
            issues.append(f"invalid ranking package: {exc}")
    if export["eligibility_policy"] != policy_record(policy):
        issues.append("eligibility policy differs from the current policy")
    if duplicate_selections(export):
        issues.append(f"duplicate selection identities: {', '.join(duplicate_selections(export))}")
    results = []
    for s in export["selections"]:
        checks, package, _ = consistency_checks(s, packages)
        current = verify(manifest, root, policy, s["candidate_id"], s["representation"], s["sha256"], now=now)
        checks["identity"] = _check(current["identity"] == "ok", f"manifest identity: {current['identity']}")
        checks["bytes"] = _check(current["file"] == "ok", f"local bytes: {current['file']}")
        now_prov, then = provenance(manifest, s["candidate_id"]), s.get("provenance_at_decision") or {}
        checks["provenance"] = _check(now_prov is not None and now_prov["candidate"] == then.get("candidate")
            and now_prov["evidence"] == then.get("evidence"),
            "manifest record and referenced evidence records equal those at decision")
        was, is_ = s.get("eligibility_at_decision") or {}, current["eligibility"] or {}
        checks["eligibility"] = _check(is_.get("status") == was.get("status") == "eligible"
            and is_.get("policy_version") == was.get("policy_version"),
            f"eligibility at decision {was.get('status')} / now {is_.get('status')}")
        # Model/config comparisons read the frozen package, never the selection's copy.
        frozen = package.ranking if package else None
        checks["model_contract"] = _check(frozen is not None and frozen["retrieval_contract"] == CONTRACT,
            "frozen ranking used the currently pinned model/preprocessing contract")
        checks["ranking_config"] = _check(frozen is not None and (config_fingerprint is None
            or frozen["ranking_config"]["fingerprint"] == config_fingerprint),
            "frozen ranking config fingerprint equals the current config" if config_fingerprint
            else "no current config supplied; recorded config retained")
        results.append(dict(candidate_id=s["candidate_id"], package_id=s["package_id"], decision=s.get("decision"),
            checks=checks, mismatches=[name for name, c in checks.items() if not c["ok"]],
            current_issues=current["issues"]))
    return dict(schema_version=REPORT_SCHEMA, export_content_sha256=export.get("content_sha256"),
                checked_at=(now or now_utc()).isoformat(), global_issues=issues,
                verified=not issues and all(not r["mismatches"] for r in results), selections=results)


def import_export(store: Store, export: dict):
    """Restore packages and decision histories atomically.

    The whole export is validated in memory and the prospective state is built and validated
    before a single write. Existing different histories are conflicts, never overwritten.
    """
    body = {k: v for k, v in export.items() if k != "content_sha256"}
    if export.get("schema_version") != EXPORT_SCHEMA or canonical_sha256(body) != export.get("content_sha256"):
        raise ValueError("refusing to import an invalid or modified export")
    packages = [Package.model_validate(raw) for raw in export["packages"]]
    by_id = {p.package_id: p for p in packages}
    if len(by_id) != len(packages):
        raise ValueError("refusing to import: duplicate ranking package")
    if duplicate_selections(export):
        raise ValueError(f"refusing to import: duplicate selection identities {duplicate_selections(export)}")
    incoming = []
    for s in export["selections"]:
        checks, _, history = consistency_checks(s, by_id)
        failed = [name for name, c in checks.items() if not c["ok"]]
        if failed:
            raise ValueError(f"refusing to import: {s.get('candidate_id')} is inconsistent with its frozen "
                             f"package or decision history ({', '.join(failed)})")
        incoming.append(CandidateRecord(package_id=s["package_id"], candidate_id=s["candidate_id"],
                                        representation=s["representation"], sha256=s["sha256"], events=history))
    summary = dict(packages_added=0, records_added=0, unchanged=0, conflicts=[])
    with store.lock:
        known = {p.package_id for p in store.state.packages}
        new_packages = [p for p in packages if p.package_id not in known]
        records = list(store.state.records)
        for record in incoming:
            existing = next((r for r in records if r.key()[:3] == record.key()[:3]), None)
            if existing is None:
                records.append(record)
                summary["records_added"] += 1
            elif existing == record:
                summary["unchanged"] += 1
            else:
                summary["conflicts"].append(dict(candidate_id=record.candidate_id, package_id=record.package_id,
                    reason="state already holds a different decision history; left unchanged"))
        summary["packages_added"] = len(new_packages)
        # Constructing State validates identities/duplicates before anything is persisted.
        prospective = State(packages=[*store.state.packages, *new_packages], records=records)
        if new_packages or summary["records_added"]:
            store.state = prospective
            store.save()
    return summary
