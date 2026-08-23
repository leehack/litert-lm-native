#!/usr/bin/env python3
"""Validate a published release result against its exact immutable transaction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from release_result import validate_published_result


def load_object(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"{label} must be valid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--release-metadata", type=Path, required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--upstream-tag", default="")
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--compatibility-tag", required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--candidate-artifact", required=True)
    args = parser.parse_args()
    try:
        validate_published_result(
            load_object(args.result, label="release result"),
            manifest=load_object(args.manifest, label="release manifest"),
            correlation_id=args.correlation_id,
            repository=args.repository,
            release_tag=args.release_tag,
            upstream_tag=args.upstream_tag or None,
            upstream_commit=args.upstream_commit,
            compatibility_tag=args.compatibility_tag,
            native_commit=args.native_commit,
            candidate_artifact=args.candidate_artifact,
            release_metadata=load_object(
                args.release_metadata, label="release metadata"
            ),
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("Validated exact published release result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
