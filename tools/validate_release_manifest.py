#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_runtime_artifacts import REQUIRED_RUNTIME_ARTIFACTS


REQUIRED_RUNTIME_ARCHIVES = [
    "litert-lm-native-runtime-android-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-android-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-linux-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-linux-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-macos-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-macos-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-windows-x64-{tag}.tar.gz",
]

REQUIRED_RELEASE_ASSETS = [
    "manifest.json",
    "SHA256SUMS",
    "litert-lm-native-prebuilts-{tag}.tar.gz",
    "litert-lm-native-official-assets-{tag}.tar.gz",
    *REQUIRED_RUNTIME_ARCHIVES,
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that a release manifest lists required runtime artifacts "
            "and, optionally, that GitHub release metadata lists required assets."
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument(
        "--release-metadata",
        type=Path,
        help="JSON from `gh release view --json assets`.",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    paths = {
        artifact.get("path")
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    }
    required = [path.as_posix() for path in REQUIRED_RUNTIME_ARTIFACTS]
    required.append(f"dist/official/{args.upstream_tag}/CLiteRTLM.xcframework.zip")
    missing = [path for path in required if path not in paths]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"Release manifest is missing required runtime paths:\n{formatted}")

    print(f"Release manifest lists {len(required)} required runtime artifacts")

    if args.release_metadata is not None:
        release = json.loads(args.release_metadata.read_text(encoding="utf-8"))
        asset_names = {
            asset.get("name")
            for asset in release.get("assets", [])
            if isinstance(asset, dict)
        }
        required_assets = [
            pattern.format(tag=args.upstream_tag) for pattern in REQUIRED_RELEASE_ASSETS
        ]
        missing_assets = [
            asset for asset in required_assets if asset not in asset_names
        ]
        if missing_assets:
            formatted = "\n".join(f"- {asset}" for asset in missing_assets)
            raise SystemExit(f"Release is missing required assets:\n{formatted}")
        print(f"Release metadata lists {len(required_assets)} required assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
