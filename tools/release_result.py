#!/usr/bin/env python3
"""Write and validate machine-readable release orchestration results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CORRELATION_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def build_result(
    *,
    manifest: dict,
    correlation_id: str,
    repository: str,
    run_id: int,
    run_attempt: int,
    run_url: str,
    approval: str,
    outcome: str,
    release_tag: str,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    native_commit: str,
    candidate_artifact: str,
    release_metadata: dict | None = None,
) -> dict:
    if not CORRELATION_RE.fullmatch(correlation_id):
        raise ValueError("invalid correlation identifier")
    if approval not in {"prepare-only", "publish"}:
        raise ValueError("invalid publication approval")
    if outcome not in {"prepared", "validated-for-publication"}:
        raise ValueError("invalid release outcome")
    for name, commit in (
        ("upstream", upstream_commit),
        ("native", native_commit),
    ):
        if not FULL_SHA_RE.fullmatch(commit):
            raise ValueError(f"invalid {name} commit")
    if manifest.get("schemaVersion") != 2:
        raise ValueError("release result requires manifest schema 2")
    if manifest.get("release", {}).get("tag") != release_tag:
        raise ValueError("manifest release tag mismatch")
    if manifest.get("upstream", {}).get("tag") != upstream_tag:
        raise ValueError("manifest upstream tag mismatch")
    if manifest.get("upstream", {}).get("commit") != upstream_commit:
        raise ValueError("manifest upstream commit mismatch")
    if manifest.get("upstream", {}).get("compatibilityTag") != compatibility_tag:
        raise ValueError("manifest compatibility tag mismatch")
    if manifest.get("native", {}).get("commit") != native_commit:
        raise ValueError("manifest native commit mismatch")

    passing_smokes = sorted(
        f"{item.get('platform')}/{item.get('arch')}"
        for item in manifest.get("realModelSmokes", [])
        if isinstance(item, dict) and item.get("result") == "pass"
    )
    result = {
        "schemaVersion": 1,
        "correlationId": correlation_id,
        "workflow": {
            "repository": repository,
            "runId": run_id,
            "runAttempt": run_attempt,
            "url": run_url,
            "nativeCommit": native_commit,
        },
        "request": {
            "publicationApproval": approval,
            "releaseTag": release_tag,
            "upstreamTag": upstream_tag,
            "upstreamCommit": upstream_commit,
            "upstreamCompatibilityTag": compatibility_tag,
            "nativeCommit": native_commit,
        },
        "outcome": outcome,
        "candidate": {"artifact": candidate_artifact},
        "validation": {
            "manifest": "pass",
            "artifactDigests": "pass",
            "platformCount": len(manifest.get("platforms", [])),
            "artifactCount": len(manifest.get("artifacts", [])),
            "passingRealModelSmokes": passing_smokes,
        },
    }
    if release_metadata is not None:
        assets = release_metadata.get("assets", [])
        digests = {
            str(asset.get("name")): str(asset.get("digest"))
            for asset in assets
            if isinstance(asset, dict) and asset.get("name") != "release-result.json"
        }
        invalid = sorted(
            name for name, digest in digests.items() if not DIGEST_RE.fullmatch(digest)
        )
        if invalid:
            raise ValueError("release assets lack GitHub SHA-256 digests: " + ", ".join(invalid))
        result["release"] = {
            "id": release_metadata.get("id"),
            "url": release_metadata.get("html_url"),
            "draftValidated": release_metadata.get("draft") is True,
            "assetDigests": digests,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--upstream-tag", default="")
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--compatibility-tag", required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--candidate-artifact", required=True)
    parser.add_argument("--release-metadata", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    release_metadata = (
        json.loads(args.release_metadata.read_text(encoding="utf-8"))
        if args.release_metadata
        else None
    )
    result = build_result(
        manifest=manifest,
        correlation_id=args.correlation_id,
        repository=args.repository,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        run_url=args.run_url,
        approval=args.approval,
        outcome=args.outcome,
        release_tag=args.release_tag,
        upstream_tag=args.upstream_tag or None,
        upstream_commit=args.upstream_commit,
        compatibility_tag=args.compatibility_tag,
        native_commit=args.native_commit,
        candidate_artifact=args.candidate_artifact,
        release_metadata=release_metadata,
    )
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
