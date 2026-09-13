#!/usr/bin/env python3
"""Fail PR qualification when its pinned source no longer matches the upstream tag."""
from __future__ import annotations

import argparse
import re

from check_upstream_release import resolve_upstream_commit


def verify_source(tag: str, expected_commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("Qualification requires an exact lowercase 40-hex commit")
    actual_commit = resolve_upstream_commit(tag)
    if actual_commit != expected_commit:
        raise ValueError(
            f"Upstream tag {tag} moved: expected {expected_commit}, got {actual_commit}; "
            "update the qualification pin and rerun all builds and real-model evidence"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    verify_source(args.tag, args.commit)
    print(f"Verified {args.tag} resolves to {args.commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
