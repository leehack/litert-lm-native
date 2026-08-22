#!/usr/bin/env python3
"""Plan deterministic creation or safe resumption of a draft release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


class PublicationStateError(ValueError):
    pass


def release_notes(
    *,
    release_tag: str,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    native_commit: str,
    correlation_id: str,
) -> str:
    return (
        f"Release {release_tag}; upstream tag {upstream_tag or '(development)'}; "
        f"upstream commit {upstream_commit}; compatibility tag {compatibility_tag}; "
        f"native commit {native_commit}; "
        f"correlation {correlation_id}."
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
    prerelease: bool,
) -> dict:
    title = f"LiteRT-LM {release_tag}"
    notes = release_notes(
        release_tag=release_tag,
        upstream_tag=upstream_tag,
        upstream_commit=upstream_commit,
        compatibility_tag=compatibility_tag,
        native_commit=native_commit,
        correlation_id=correlation_id,
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
    if existing.get("draft") is not True:
        raise PublicationStateError(
            f"release collision: published release {release_tag} is immutable"
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
        raise PublicationStateError("matching draft release has no numeric id")
    return {
        "action": "resume",
        "releaseId": release_id,
        "title": title,
        "notes": notes,
        "prerelease": prerelease,
    }


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
    parser.add_argument("--prerelease", choices=("true", "false"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    releases = json.loads(args.releases.read_text(encoding="utf-8"))
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
            prerelease=args.prerelease == "true",
        )
    except PublicationStateError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
