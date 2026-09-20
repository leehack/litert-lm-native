#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from litert_lm_symbols import is_at_least
from windows_dxc import dxc_license_paths, dxc_runtime_paths, requires_dxc

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_RUNTIME_ARTIFACTS = [
    Path("bin/android/arm64/libLiteRtLm.so"),
    Path("bin/android/x64/libLiteRtLm.so"),
    Path("bin/ios/arm64/LiteRtLm.framework/LiteRtLm"),
    Path("bin/ios/arm64/CLiteRTLM.framework/CLiteRTLM"),
    Path("bin/ios/arm64-sim/LiteRtLm.framework/LiteRtLm"),
    Path("bin/ios/arm64-sim/CLiteRTLM.framework/CLiteRTLM"),
    Path("bin/linux/arm64/libLiteRtLm.so"),
    Path("bin/linux/x64/libLiteRtLm.so"),
    Path("bin/macos/arm64/libCLiteRTLM_mac.dylib"),
    Path("bin/macos/arm64/libLiteRtLm.dylib"),
    Path("bin/macos/x64/libCLiteRTLM_mac.dylib"),
    Path("bin/macos/x64/libLiteRtLm.dylib"),
    Path("bin/windows/x64/LiteRtLm.dll"),
]

V0_16_IOS_GPU_ARTIFACTS = [
    Path("bin/ios/arm64/LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator"),
    Path("bin/ios/arm64/LiteRtTopKMetalSampler.framework/LiteRtTopKMetalSampler"),
    Path("bin/ios/arm64-sim/LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator"),
    Path("bin/ios/arm64-sim/LiteRtTopKMetalSampler.framework/LiteRtTopKMetalSampler"),
]

OFFICIAL_APPLE_RUNTIME_ARCHIVES = (
    "CLiteRTLM.xcframework.zip",
    "CLiteRTLM_mac.xcframework.zip",
)


def required_runtime_artifacts(
    upstream_tag: str, *, include_official_assets: bool = True
) -> list[Path]:
    required = list(REQUIRED_RUNTIME_ARTIFACTS)
    if is_at_least(upstream_tag, (0, 16, 0)):
        required.extend(V0_16_IOS_GPU_ARTIFACTS)
    if requires_dxc(upstream_tag):
        # Dawn's D3D12 backend loads this pair by name; without it Windows GPU
        # engine creation fails before any adapter work.
        required.extend(dxc_runtime_paths())
    if include_official_assets:
        required.extend(
            Path("dist") / "official" / upstream_tag / archive
            for archive in OFFICIAL_APPLE_RUNTIME_ARCHIVES
        )
    return required


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that release packaging contains upstream runtime libraries."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument(
        "--allow-missing-official-assets",
        action="store_true",
        help=(
            "Validate source-built runtimes without requiring the upstream "
            "official Apple release archives."
        ),
    )
    args = parser.parse_args()

    include_official_assets = not args.allow_missing_official_assets
    required = required_runtime_artifacts(
        args.upstream_tag, include_official_assets=include_official_assets
    )
    # DXC licence texts ship in the runtime archive but are not native
    # artifacts, so the manifest never records them; check them here.
    required_with_licences = required + (
        dxc_license_paths() if requires_dxc(args.upstream_tag) else []
    )
    missing = [
        path for path in required_with_licences if not (REPO_ROOT / path).is_file()
    ]
    if missing:
        formatted = "\n".join(f"- {path.as_posix()}" for path in missing)
        raise SystemExit(f"Missing required runtime artifacts:\n{formatted}")

    print(f"Validated {len(required_with_licences)} required runtime artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
