#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_runtime_artifacts import REQUIRED_RUNTIME_ARTIFACTS


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that a release manifest lists required runtime artifacts."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--upstream-tag", required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    paths = {
        artifact.get("path")
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    }
    required = [path.as_posix() for path in REQUIRED_RUNTIME_ARTIFACTS]
    required.append(f"dist/{args.upstream_tag}/CLiteRTLM.xcframework.zip")
    missing = [path for path in required if path not in paths]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"Release manifest is missing required runtime paths:\n{formatted}")

    print(f"Release manifest lists {len(required)} required runtime artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
