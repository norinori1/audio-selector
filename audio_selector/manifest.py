"""Versioned exact-byte provenance and explicit, fail-closed usage policy.

Recorded permissions are human/source evidence assertions, never legal inference.
All local references resolve relative to the manifest file, not the caller's cwd.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Permission = Literal["allowed", "denied", "unknown"]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Blob(Model):
    path: Text
    sha256: Digest
    size: Annotated[int, Field(gt=0)]
    media_type: Text
    filename: Text


class Evidence(Model):
    id: Text
    url: Text
    snapshot: Blob
    checked: date
    # The captured source evidence must explicitly identify these exact assets.
    asset_sha256s: Annotated[list[Digest], Field(min_length=1)]
    notes: Text


class Rights(Model):
    license_name: Text
    license_url: Text
    evidence_ids: Annotated[list[Text], Field(min_length=1)]
    commercial: Permission = "unknown"
    modification: Permission = "unknown"
    game_embedding: Permission = "unknown"
    redistribution: Permission = "unknown"
    attribution: Literal["required", "not-required", "unknown"] = "unknown"
    attribution_text: str | None = None
    redistribution_restrictions: str | None = None
    content_id_notes: str | None = None


class Candidate(Model):
    id: Text
    provider: Text
    source_asset_id: str | None = None
    asset_url: Text
    author: Text
    acquisition_source: Text
    acquired: date
    metadata_evidence_ids: Annotated[list[Text], Field(min_length=1)]
    original: Blob
    preview: Blob | None = None
    kind: Literal["original", "derivative"] = "original"
    parent_id: str | None = None
    transformation: str | None = None
    rights: Rights | None = None

    @model_validator(mode="after")
    def lineage(self):
        if self.kind == "derivative" and (not self.parent_id or not self.transformation):
            raise ValueError("derivative requires parent_id and transformation")
        if self.kind == "original" and (self.parent_id or self.transformation):
            raise ValueError("original cannot declare derivative lineage")
        return self


class Manifest(Model):
    schema_version: Literal["1.0"] = "1.0"
    candidates: list[Candidate]
    evidence: list[Evidence]

    @model_validator(mode="after")
    def references(self):
        ids = [c.id for c in self.candidates]
        evidence_ids = [e.id for e in self.evidence]
        if len(ids) != len(set(ids)) or len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate candidate/evidence IDs")
        by_id = {c.id: c for c in self.candidates}
        for c in self.candidates:
            refs = c.metadata_evidence_ids + (c.rights.evidence_ids if c.rights else [])
            if not set(refs) <= set(evidence_ids):
                raise ValueError(f"{c.id}: missing evidence reference")
            visited = {c.id}
            parent = c.parent_id
            while parent:
                if parent not in by_id or parent in visited:
                    raise ValueError(f"{c.id}: missing parent or cyclic lineage")
                visited.add(parent)
                parent = by_id[parent].parent_id
        return self


class Policy(Model):
    version: Literal["commercial-game/1.0"] = "commercial-game/1.0"
    intended_use: Literal["commercial-game"] = "commercial-game"
    max_evidence_age_days: Annotated[int, Field(ge=0)] = 365
    allow_preview: bool = False
    fulfilled_attribution_ids: frozenset[str] = frozenset()
    require_modification: bool = False
    require_standalone_redistribution: bool = False


class Decision(Model):
    candidate_id: str
    intended_use: str
    policy_version: str
    status: Literal["eligible", "ineligible", "review-required"]
    reasons: tuple[str, ...]
    decided_at: datetime
    selected_sha256: str


def load(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def verify(blob: Blob, root: Path) -> bool:
    path = root / blob.path
    try:
        return path.is_file() and path.stat().st_size == blob.size and sha256(path) == blob.sha256
    except OSError:
        return False


def evaluate(manifest: Manifest, candidate_id: str, root: Path, policy: Policy = Policy(),
             *, representation: Literal["original", "preview"] = "original",
             now: datetime | None = None) -> Decision:
    now = now or datetime.now(timezone.utc)
    by_id = {c.id: c for c in manifest.candidates}
    c = by_id[candidate_id]
    selected = c.original if representation == "original" else c.preview
    reviews, denials = [], []
    if representation == "preview" and not policy.allow_preview:
        denials.append("preview excluded by policy")
    if selected is None:
        reviews.append("selected representation missing")
    elif not verify(selected, root):
        reviews.append("selected bytes missing or hash/size mismatch")
    if c.acquired > now.date():
        reviews.append("acquisition date in future")
    evidence = {e.id: e for e in manifest.evidence}
    refs = set(c.metadata_evidence_ids + (c.rights.evidence_ids if c.rights else []))
    for ref in sorted(refs):
        e = evidence[ref]
        age = (now.date() - e.checked).days
        if age < 0 or age > policy.max_evidence_age_days:
            reviews.append(f"{ref}: future/stale evidence")
        if not verify(e.snapshot, root):
            reviews.append(f"{ref}: evidence snapshot missing or changed")
        if selected is None or selected.sha256 not in e.asset_sha256s:
            reviews.append(f"{ref}: evidence not bound to selected bytes")
    if c.rights is None:
        reviews.append("license evidence missing")
    else:
        required = ["commercial", "game_embedding"]
        if c.kind == "derivative" or policy.require_modification:
            required.append("modification")
        if policy.require_standalone_redistribution:
            required.append("redistribution")
        for key in required:
            permission = getattr(c.rights, key)
            if permission == "denied":
                denials.append(f"{key}: denied")
            elif permission != "allowed":
                reviews.append(f"{key}: unknown")
        if c.rights.attribution == "unknown":
            reviews.append("attribution unresolved")
        elif c.rights.attribution == "required" and (
            not c.rights.attribution_text or c.id not in policy.fulfilled_attribution_ids
        ):
            reviews.append("required attribution not fulfilled")
        if c.rights.redistribution_restrictions is None or c.rights.content_id_notes is None:
            reviews.append("redistribution/claim notes unresolved")
    if c.parent_id:
        parent_policy = policy.model_copy(update={"require_modification": True})
        parent = evaluate(manifest, c.parent_id, root, parent_policy, now=now)
        if parent.status != "eligible":
            reviews.append(f"parent {c.parent_id}: {parent.status} ({'; '.join(parent.reasons)})")
    return Decision(candidate_id=c.id, intended_use=policy.intended_use,
                    policy_version=policy.version,
                    status="ineligible" if denials else "review-required" if reviews else "eligible",
                    reasons=tuple(denials + reviews) or ("recorded evidence satisfies explicit policy",),
                    decided_at=now, selected_sha256=selected.sha256 if selected else "")


def eligible_candidates(manifest: Manifest, root: Path, policy: Policy = Policy()) -> list[Candidate]:
    return [c for c in manifest.candidates if evaluate(manifest, c.id, root, policy).status == "eligible"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--require-all-eligible", action="store_true")
    parser.add_argument("--hash", type=Path)
    parser.add_argument("--schema", action="store_true")
    args = parser.parse_args()
    if args.hash:
        print(sha256(args.hash))
        return
    if args.schema:
        print(json.dumps(Manifest.model_json_schema(), indent=2))
        return
    try:
        if not args.manifest:
            parser.error("manifest required")
        manifest = load(args.manifest)
        policy = Policy.model_validate_json(args.policy.read_text()) if args.policy else Policy()
        decisions = [evaluate(manifest, c.id, args.manifest.resolve().parent, policy)
                     for c in manifest.candidates]
        print(json.dumps([d.model_dump(mode="json") for d in decisions], indent=2))
        # Validation includes referenced byte integrity, independently of permissive rights.
        blobs = [b for c in manifest.candidates for b in [c.original, c.preview] if b]
        blobs += [e.snapshot for e in manifest.evidence]
        if not all(verify(b, args.manifest.resolve().parent) for b in blobs):
            sys.exit(2)
        if args.require_all_eligible and any(d.status != "eligible" for d in decisions):
            sys.exit(3)
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
