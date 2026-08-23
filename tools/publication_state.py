#!/usr/bin/env python3
"""Plan deterministic creation or safe resumption of a draft release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


class PublicationStateError(ValueError):
    pass


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def release_notes(
    *,
    release_tag: str,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    native_commit: str,
    correlation_id: str,
    workflow_run_id: int,
) -> str:
    if not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        raise PublicationStateError("workflow run ID must be a positive integer")
    return (
        f"Release {release_tag}; upstream tag {upstream_tag or '(development)'}; "
        f"upstream commit {upstream_commit}; compatibility tag {compatibility_tag}; "
        f"native commit {native_commit}; "
        f"correlation {correlation_id}; workflow run {workflow_run_id}."
    )


def plan_publication(
    releases: list[dict],
    *,
    approval: str,
    release_tag: str,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    native_commit: str,
    correlation_id: str,
    workflow_run_id: int,
    prerelease: bool,
    allow_published_exact: bool = False,
) -> dict:
    if any(not isinstance(item, dict) for item in releases):
        raise PublicationStateError("release metadata entries must be objects")
    title = f"LiteRT-LM {release_tag}"
    notes = release_notes(
        release_tag=release_tag,
        upstream_tag=upstream_tag,
        upstream_commit=upstream_commit,
        compatibility_tag=compatibility_tag,
        native_commit=native_commit,
        correlation_id=correlation_id,
        workflow_run_id=workflow_run_id,
    )
    matches = [item for item in releases if item.get("tag_name") == release_tag]
    if len(matches) > 1:
        raise PublicationStateError(
            f"release collision: multiple releases claim {release_tag}"
        )
    if not matches:
        return {
            "action": "create",
            "releaseId": None,
            "title": title,
            "notes": notes,
            "prerelease": prerelease,
        }

    existing = matches[0]
    if approval != "publish":
        raise PublicationStateError(
            f"release collision: {release_tag} already has a release record"
        )
    expected = {
        "target_commitish": native_commit,
        "name": title,
        "body": notes,
        "prerelease": prerelease,
    }
    mismatches = [
        key for key, value in expected.items() if existing.get(key) != value
    ]
    if mismatches:
        raise PublicationStateError(
            f"release collision: draft {release_tag} does not match exact inputs: "
            + ", ".join(mismatches)
        )
    release_id = existing.get("id")
    if not isinstance(release_id, int):
        raise PublicationStateError("matching release has no numeric id")
    if existing.get("draft") is not True:
        if not allow_published_exact:
            raise PublicationStateError(
                f"release collision: published release {release_tag} is immutable"
            )
        return {
            "action": "verify-published",
            "releaseId": release_id,
            "title": title,
            "notes": notes,
            "prerelease": prerelease,
        }
    return {
        "action": "resume",
        "releaseId": release_id,
        "title": title,
        "notes": notes,
        "prerelease": prerelease,
    }


def validate_tag_ref(tag_ref: dict, *, release_tag: str, native_commit: str) -> None:
    if not isinstance(tag_ref, dict):
        raise PublicationStateError("candidate tag metadata must be an object")
    if tag_ref.get("ref") != f"refs/tags/{release_tag}":
        raise PublicationStateError("candidate tag ref does not match release tag")
    target = tag_ref.get("object")
    if not isinstance(target, dict):
        raise PublicationStateError("candidate tag target metadata must be an object")
    if target.get("type") != "commit" or target.get("sha") != native_commit:
        raise PublicationStateError(
            "candidate tag must be a lightweight ref to the exact native commit"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_candidate_assets(
    release: dict,
    *,
    candidate_dir: Path,
    release_result: Path | None = None,
) -> None:
    release_dir = candidate_dir / "release"
    required_top_level = {
        "manifest.json": candidate_dir / "manifest.json",
        "SHA256SUMS": candidate_dir / "SHA256SUMS",
        "release-result.json": release_result or candidate_dir / "release-result.json",
    }
    if not release_dir.is_dir():
        raise PublicationStateError("candidate release directory is missing")
    expected_files = dict(required_top_level)
    for path in release_dir.iterdir():
        if path.is_symlink() or not path.is_file():
            raise PublicationStateError(
                f"candidate release entry must be a regular file: {path.name}"
            )
        if path.name in expected_files:
            raise PublicationStateError(f"duplicate candidate asset name: {path.name}")
        expected_files[path.name] = path
    for name, path in expected_files.items():
        if path.is_symlink() or not path.is_file():
            raise PublicationStateError(f"candidate asset is missing: {name}")

    assets = release.get("assets")
    if not isinstance(assets, list) or any(not isinstance(item, dict) for item in assets):
        raise PublicationStateError("release asset metadata must be a list of objects")
    actual_by_name: dict[str, dict] = {}
    for asset in assets:
        name = asset.get("name")
        if not isinstance(name, str) or not name:
            raise PublicationStateError("release asset name is invalid")
        if name in actual_by_name:
            raise PublicationStateError(f"duplicate release asset name: {name}")
        actual_by_name[name] = asset
    if set(actual_by_name) != set(expected_files):
        missing = sorted(set(expected_files) - set(actual_by_name))
        unexpected = sorted(set(actual_by_name) - set(expected_files))
        raise PublicationStateError(
            f"release asset inventory mismatch; missing={missing}, unexpected={unexpected}"
        )
    for name, path in expected_files.items():
        asset = actual_by_name[name]
        expected_digest = f"sha256:{_sha256(path)}"
        if asset.get("state") != "uploaded":
            raise PublicationStateError(f"release asset is not uploaded: {name}")
        if asset.get("size") != path.stat().st_size:
            raise PublicationStateError(f"release asset size mismatch: {name}")
        digest = asset.get("digest")
        if not isinstance(digest, str) or DIGEST_RE.fullmatch(digest) is None:
            raise PublicationStateError(f"release asset digest is invalid: {name}")
        if digest != expected_digest:
            raise PublicationStateError(f"release asset digest mismatch: {name}")


def _load_json(path: Path, *, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicationStateError(
            f"{label} must be valid UTF-8 JSON: {error}"
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--approval", choices=("prepare-only", "publish"), required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--upstream-tag", default="")
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--compatibility-tag", required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--prerelease", choices=("true", "false"), required=True)
    parser.add_argument("--tag-ref", type=Path)
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--release-result", type=Path)
    parser.add_argument("--allow-published-exact", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        releases = _load_json(args.releases, label="release metadata")
    except PublicationStateError as error:
        raise SystemExit(str(error)) from error
    if not isinstance(releases, list):
        raise SystemExit("release metadata must be a JSON list")
    try:
        plan = plan_publication(
            releases,
            approval=args.approval,
            release_tag=args.release_tag,
            upstream_tag=args.upstream_tag or None,
            upstream_commit=args.upstream_commit,
            compatibility_tag=args.compatibility_tag,
            native_commit=args.native_commit,
            correlation_id=args.correlation_id,
            workflow_run_id=args.workflow_run_id,
            prerelease=args.prerelease == "true",
            allow_published_exact=args.allow_published_exact,
        )
        matches = [item for item in releases if item.get("tag_name") == args.release_tag]
        if args.tag_ref is not None:
            if plan["action"] not in {"resume", "verify-published"} or len(matches) != 1:
                raise PublicationStateError(
                    "candidate tag validation requires one exact release transaction"
                )
            tag_ref = _load_json(args.tag_ref, label="candidate tag metadata")
            validate_tag_ref(
                tag_ref,
                release_tag=args.release_tag,
                native_commit=args.native_commit,
            )
        if args.candidate_dir is not None:
            if plan["action"] not in {"resume", "verify-published"} or len(matches) != 1:
                raise PublicationStateError(
                    "candidate asset validation requires one exact release transaction"
                )
            validate_candidate_assets(
                matches[0],
                candidate_dir=args.candidate_dir,
                release_result=args.release_result,
            )
    except PublicationStateError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
