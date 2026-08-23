#!/usr/bin/env python3
"""Write and validate machine-readable release orchestration results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from publication_state import release_notes


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CORRELATION_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def load_json_object(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


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
    if not isinstance(manifest, dict):
        raise ValueError("release manifest must be an object")
    if not CORRELATION_RE.fullmatch(correlation_id):
        raise ValueError("invalid correlation identifier")
    if approval not in {"prepare-only", "publish"}:
        raise ValueError("invalid publication approval")
    if outcome not in {"prepared", "validated-for-publication"}:
        raise ValueError("invalid release outcome")
    if run_id <= 0 or run_attempt <= 0:
        raise ValueError("invalid workflow run identity")
    if run_url != f"https://github.com/{repository}/actions/runs/{run_id}":
        raise ValueError("invalid workflow run URL")
    for name, commit in (
        ("upstream", upstream_commit),
        ("native", native_commit),
    ):
        if not FULL_SHA_RE.fullmatch(commit):
            raise ValueError(f"invalid {name} commit")
    if manifest.get("schemaVersion") != 2:
        raise ValueError("release result requires manifest schema 2")
    identity_sections = {}
    for name in ("release", "upstream", "native"):
        section = manifest.get(name)
        if not isinstance(section, dict):
            raise ValueError(f"manifest {name} must be an object")
        identity_sections[name] = section
    release = identity_sections["release"]
    upstream = identity_sections["upstream"]
    native = identity_sections["native"]
    for name in ("platforms", "artifacts", "realModelSmokes"):
        items = manifest.get(name)
        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise ValueError(f"manifest {name} must be a list of objects")
    if release.get("tag") != release_tag:
        raise ValueError("manifest release tag mismatch")
    if upstream.get("tag") != upstream_tag:
        raise ValueError("manifest upstream tag mismatch")
    if upstream.get("commit") != upstream_commit:
        raise ValueError("manifest upstream commit mismatch")
    if upstream.get("compatibilityTag") != compatibility_tag:
        raise ValueError("manifest compatibility tag mismatch")
    if native.get("commit") != native_commit:
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
        expected_release = {
            "tag_name": release_tag,
            "target_commitish": native_commit,
            "name": f"LiteRT-LM {release_tag}",
            "body": release_notes(
                release_tag=release_tag,
                upstream_tag=upstream_tag,
                upstream_commit=upstream_commit,
                compatibility_tag=compatibility_tag,
                native_commit=native_commit,
                correlation_id=correlation_id,
                workflow_run_id=run_id,
            ),
            "draft": True,
            "prerelease": release.get("githubPrerelease"),
        }
        if not isinstance(release_metadata, dict):
            raise ValueError("release metadata must be an object")
        mismatches = [
            key
            for key, expected in expected_release.items()
            if release_metadata.get(key) != expected
        ]
        if mismatches:
            raise ValueError(
                "release metadata does not match exact transaction: "
                + ", ".join(mismatches)
            )
        if not isinstance(release_metadata.get("id"), int) or not isinstance(
            release_metadata.get("html_url"), str
        ):
            raise ValueError("release metadata is missing identity fields")
        assets = release_metadata.get("assets", [])
        if not isinstance(assets, list) or any(
            not isinstance(asset, dict) for asset in assets
        ):
            raise ValueError("release assets must be a list of objects")
        digests = {}
        seen_asset_names: set[str] = set()
        for asset in assets:
            name = asset.get("name")
            digest = asset.get("digest")
            if not isinstance(name, str) or not name or not isinstance(digest, str):
                raise ValueError("release assets require non-empty names and digests")
            if name in seen_asset_names:
                raise ValueError(f"release assets contain duplicate name: {name}")
            seen_asset_names.add(name)
            if name != "release-result.json":
                digests[name] = digest
        invalid = sorted(
            name for name, digest in digests.items() if not DIGEST_RE.fullmatch(digest)
        )
        if invalid:
            raise ValueError("release assets lack GitHub SHA-256 digests: " + ", ".join(invalid))
        result["release"] = {
            "id": release_metadata.get("id"),
            "url": release_metadata.get("html_url"),
            "draftValidated": True,
            "assetDigests": digests,
        }
    return result


def validate_published_result(
    result: dict,
    *,
    manifest: dict,
    correlation_id: str,
    repository: str,
    release_tag: str,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    native_commit: str,
    candidate_artifact: str,
    release_metadata: dict,
) -> None:
    if not isinstance(result, dict):
        raise ValueError("published release result must be an object")
    workflow = result.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("published release result is missing workflow identity")
    run_id = workflow.get("runId")
    run_attempt = workflow.get("runAttempt")
    run_url = workflow.get("url")
    if (
        not isinstance(run_id, int)
        or run_id <= 0
        or not isinstance(run_attempt, int)
        or run_attempt <= 0
        or not isinstance(run_url, str)
        or not run_url
    ):
        raise ValueError("published release result workflow identity is invalid")
    expected_run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    if run_url != expected_run_url:
        raise ValueError("published release result workflow URL is invalid")
    if release_metadata.get("draft") is not False:
        raise ValueError("published release metadata must not be a draft")
    validation_metadata = dict(release_metadata)
    validation_metadata["draft"] = True
    expected = build_result(
        manifest=manifest,
        correlation_id=correlation_id,
        repository=repository,
        run_id=run_id,
        run_attempt=run_attempt,
        run_url=run_url,
        approval="publish",
        outcome="validated-for-publication",
        release_tag=release_tag,
        upstream_tag=upstream_tag,
        upstream_commit=upstream_commit,
        compatibility_tag=compatibility_tag,
        native_commit=native_commit,
        candidate_artifact=candidate_artifact,
        release_metadata=validation_metadata,
    )
    if result != expected:
        raise ValueError("published release result does not match exact transaction")


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
    try:
        manifest = load_json_object(args.manifest, label="release manifest")
        release_metadata = (
            load_json_object(args.release_metadata, label="release metadata")
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
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
