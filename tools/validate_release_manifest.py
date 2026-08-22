#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from litert_lm_symbols import is_at_least
from prebuilt_overrides import prebuilt_override_manifest
from release_version_policy import parse_upstream, validate_pair
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

V0_16_IOS_GPU_SPM_XCFRAMEWORKS = [
    "litert-lm-native-apple-LiteRtMetalAccelerator-xcframework-{tag}.zip",
    "litert-lm-native-apple-LiteRtTopKMetalSampler-xcframework-{tag}.zip",
]


def required_spm_assets(compatibility_tag: str) -> list[str]:
    assets = list(REQUIRED_SPM_XCFRAMEWORKS)
    if is_at_least(compatibility_tag, (0, 16, 0)):
        assets.extend(V0_16_IOS_GPU_SPM_XCFRAMEWORKS)
    return assets


def validate_schema_2_identity(
    manifest: dict,
    *,
    upstream_tag: str | None,
    upstream_commit: str | None,
    compatibility_tag: str | None,
    native_commit: str | None,
    release_tag: str,
) -> tuple[str, bool]:
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict):
        raise SystemExit("Release manifest is missing upstream provenance")
    if upstream.get("tag") != upstream_tag:
        raise SystemExit(
            "Release manifest upstream tag mismatch: "
            f"expected {upstream_tag}, got {upstream.get('tag')}"
        )
    manifest_upstream_commit = upstream.get("commit")
    if not isinstance(manifest_upstream_commit, str) or len(manifest_upstream_commit) != 40:
        raise SystemExit("Release manifest upstream commit must be a full SHA")
    if upstream_commit and manifest_upstream_commit != upstream_commit:
        raise SystemExit(
            "Release manifest upstream commit mismatch: "
            f"expected {upstream_commit}, got {manifest_upstream_commit}"
        )
    manifest_compatibility = upstream.get("compatibilityTag")
    if not isinstance(manifest_compatibility, str):
        raise SystemExit("Release manifest is missing compatibilityTag")
    if compatibility_tag and manifest_compatibility != compatibility_tag:
        raise SystemExit(
            "Release manifest compatibility tag mismatch: "
            f"expected {compatibility_tag}, got {manifest_compatibility}"
        )

    native = manifest.get("native")
    if not isinstance(native, dict):
        raise SystemExit("Release manifest is missing native provenance")
    manifest_native_commit = native.get("commit")
    if not isinstance(manifest_native_commit, str) or len(manifest_native_commit) != 40:
        raise SystemExit("Release manifest native commit must be a full SHA")
    if native_commit and manifest_native_commit != native_commit:
        raise SystemExit(
            "Release manifest native commit mismatch: "
            f"expected {native_commit}, got {manifest_native_commit}"
        )

    release = manifest.get("release")
    if not isinstance(release, dict) or release.get("tag") != release_tag:
        actual = release.get("tag") if isinstance(release, dict) else None
        raise SystemExit(
            "Release manifest native release tag mismatch: "
            f"expected {release_tag}, got {actual}"
        )
    identity = parse_upstream(
        upstream_tag=upstream_tag,
        upstream_commit=manifest_upstream_commit,
        compatibility_tag=manifest_compatibility,
    )
    parsed_release = validate_pair(identity, release_tag)
    if release.get("channel") != parsed_release.channel:
        raise SystemExit("Release manifest channel does not match release tag")
    if release.get("kind") != parsed_release.kind:
        raise SystemExit("Release manifest kind does not match release tag")
    if release.get("rebuild") != parsed_release.rebuild:
        raise SystemExit("Release manifest rebuild does not match release tag")

    expected_overrides = prebuilt_override_manifest(manifest_compatibility)
    if upstream.get("prebuiltOverrides", []) != expected_overrides:
        raise SystemExit(
            "Release manifest prebuilt override provenance mismatch: "
            f"expected {expected_overrides}, got {upstream.get('prebuiltOverrides')}"
        )
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        raise SystemExit("Release manifest is missing capabilities")
    official_assets = capabilities.get("officialUpstreamAssets") is True
    if upstream_tag is not None and not official_assets:
        raise SystemExit("Stable releases must include official upstream assets")
    return manifest_compatibility, official_assets


def validate_legacy_identity(
    manifest: dict, *, upstream_tag: str | None, release_tag: str
) -> tuple[str, bool]:
    if upstream_tag is None:
        raise SystemExit("Legacy schema 1 manifests require --upstream-tag")
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict) or upstream.get("tag") != upstream_tag:
        actual = upstream.get("tag") if isinstance(upstream, dict) else None
        raise SystemExit(
            "Release manifest upstream tag mismatch: "
            f"expected {upstream_tag}, got {actual}"
        )
    release = manifest.get("release")
    if not isinstance(release, dict) or release.get("tag") != release_tag:
        actual = release.get("tag") if isinstance(release, dict) else None
        raise SystemExit(
            "Release manifest native release tag mismatch: "
            f"expected {release_tag}, got {actual}"
        )
    expected_overrides = prebuilt_override_manifest(upstream_tag)
    if upstream.get("prebuiltOverrides", []) != expected_overrides:
        raise SystemExit("Legacy manifest prebuilt override provenance mismatch")
    return upstream_tag, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate release manifest identity, payload, and evidence."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--upstream-tag", default="")
    parser.add_argument("--upstream-commit")
    parser.add_argument("--compatibility-tag")
    parser.add_argument("--native-commit")
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--release-metadata", type=Path)
    parser.add_argument(
        "--require-smoke",
        action="append",
        default=[],
        metavar="PLATFORM/ARCH",
    )
    args = parser.parse_args()
    upstream_tag = args.upstream_tag or None

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    schema_version = manifest.get("schemaVersion")
    if schema_version == 2:
        compatibility_tag, official_assets = validate_schema_2_identity(
            manifest,
            upstream_tag=upstream_tag,
            upstream_commit=args.upstream_commit,
            compatibility_tag=args.compatibility_tag,
            native_commit=args.native_commit,
            release_tag=args.release_tag,
        )
    elif schema_version == 1:
        compatibility_tag, official_assets = validate_legacy_identity(
            manifest, upstream_tag=upstream_tag, release_tag=args.release_tag
        )
    else:
        raise SystemExit(f"Unsupported release manifest schemaVersion {schema_version}")

    paths = {
        artifact.get("path")
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    }
    required = [
        path.as_posix()
        for path in required_runtime_artifacts(
            compatibility_tag, include_official_assets=official_assets
        )
    ]
    required_spm = required_spm_assets(compatibility_tag)
    required.extend(
        f"dist/spm/{args.release_tag}/{asset.format(tag=args.release_tag)}"
        for asset in required_spm
    )
    missing = [path for path in required if path not in paths]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"Release manifest is missing required runtime paths:\n{formatted}")

    smokes = manifest.get("realModelSmokes", [])
    if not isinstance(smokes, list):
        raise SystemExit("Release manifest realModelSmokes must be a list")
    passed_smokes = {
        f"{smoke.get('platform')}/{smoke.get('arch')}"
        for smoke in smokes
        if isinstance(smoke, dict) and smoke.get("result") == "pass"
    }
    missing_smokes = sorted(set(args.require_smoke) - passed_smokes)
    if missing_smokes:
        raise SystemExit(
            "Release manifest is missing required real-model smoke evidence: "
            + ", ".join(missing_smokes)
        )
    print(
        f"Release manifest lists {len(required)} required runtime artifacts and "
        f"{len(passed_smokes)} passing smoke target(s)"
    )

    if args.release_metadata is not None:
        release_metadata = json.loads(
            args.release_metadata.read_text(encoding="utf-8")
        )
        asset_names = {
            asset.get("name")
            for asset in release_metadata.get("assets", [])
            if isinstance(asset, dict)
        }
        spm_assets = sorted(
            Path(path).name
            for path in paths
            if isinstance(path, str)
            and path.startswith(f"dist/spm/{args.release_tag}/")
            and path.endswith(".zip")
        )
        required_assets = [
            "manifest.json",
            "SHA256SUMS",
            "release-result.json",
            f"litert-lm-native-prebuilts-{args.release_tag}.tar.gz",
            *[
                pattern.format(tag=args.release_tag)
                for pattern in REQUIRED_RUNTIME_ARCHIVES
            ],
            *[pattern.format(tag=args.release_tag) for pattern in required_spm],
            *spm_assets,
        ]
        if official_assets:
            required_assets.append(
                f"litert-lm-native-official-assets-{args.release_tag}.tar.gz"
            )
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
