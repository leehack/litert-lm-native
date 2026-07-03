#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from litert_lm_symbols import is_at_least
from validate_runtime_artifacts import required_runtime_artifacts


REQUIRED_RUNTIME_ARCHIVES = [
    "litert-lm-native-runtime-android-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-android-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-ios-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-ios-arm64-sim-{tag}.tar.gz",
    "litert-lm-native-runtime-linux-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-linux-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-macos-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-macos-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-windows-x64-{tag}.tar.gz",
]

REQUIRED_SPM_XCFRAMEWORKS = [
    "litert-lm-native-apple-CLiteRTLM-xcframework-{tag}.zip",
    "litert-lm-native-apple-CLiteRTLMMac-xcframework-{tag}.zip",
    "litert-lm-native-apple-LiteRtLm-xcframework-{tag}.zip",
]

V0_14_REQUIRED_SPM_XCFRAMEWORKS = [
    "litert-lm-native-apple-GemmaModelConstraintProvider-xcframework-{tag}.zip",
]

BASE_REQUIRED_RELEASE_ASSETS = [
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
        "--release-tag",
        help="Native release tag used in release asset names. Defaults to upstream-tag.",
    )
    parser.add_argument(
        "--release-metadata",
        type=Path,
        help="JSON from `gh release view --json assets`.",
    )
    args = parser.parse_args()
    release_tag = args.release_tag or args.upstream_tag

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    upstream = manifest.get("upstream", {})
    if not isinstance(upstream, dict) or upstream.get("tag") != args.upstream_tag:
        actual = upstream.get("tag") if isinstance(upstream, dict) else None
        raise SystemExit(
            "Release manifest upstream tag mismatch: "
            f"expected {args.upstream_tag}, got {actual}"
        )
    release = manifest.get("release", {})
    if not isinstance(release, dict) or release.get("tag") != release_tag:
        actual = release.get("tag") if isinstance(release, dict) else None
        raise SystemExit(
            "Release manifest native release tag mismatch: "
            f"expected {release_tag}, got {actual}"
        )
    paths = {
        artifact.get("path")
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    }
    required = [path.as_posix() for path in required_runtime_artifacts(args.upstream_tag)]
    if not is_at_least(args.upstream_tag, (0, 14, 0)):
        required.extend(
            [
                f"dist/official/{args.upstream_tag}/CLiteRTLM.xcframework.zip",
                f"dist/official/{args.upstream_tag}/CLiteRTLM_mac.xcframework.zip",
            ]
        )
    required_spm_xcframeworks = list(REQUIRED_SPM_XCFRAMEWORKS)
    if is_at_least(args.upstream_tag, (0, 14, 0)):
        required_spm_xcframeworks.extend(V0_14_REQUIRED_SPM_XCFRAMEWORKS)
    required.extend(
        f"dist/spm/{release_tag}/{asset.format(tag=release_tag)}"
        for asset in required_spm_xcframeworks
    )
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
        spm_assets = sorted(
            Path(path).name
            for path in paths
            if isinstance(path, str)
            and path.startswith(f"dist/spm/{release_tag}/")
            and path.endswith(".zip")
        )
        required_assets = [
            pattern.format(tag=release_tag)
            for pattern in BASE_REQUIRED_RELEASE_ASSETS
        ]
        required_assets.extend(
            pattern.format(tag=release_tag)
            for pattern in required_spm_xcframeworks
        )
        required_assets.extend(spm_assets)
        required_assets = sorted(set(required_assets))
        missing_assets = [
            asset for asset in required_assets if asset not in asset_names
        ]
        if missing_assets:
            formatted = "\n".join(f"- {asset}" for asset in missing_assets)
            raise SystemExit(f"Release is missing required assets:\n{formatted}")
        unexpected_assets = sorted(asset_names - set(required_assets))
        if unexpected_assets:
            formatted = "\n".join(f"- {asset}" for asset in unexpected_assets)
            raise SystemExit(f"Release has unexpected assets:\n{formatted}")
        print(f"Release metadata lists {len(required_assets)} required assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
