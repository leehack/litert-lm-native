#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from litert_lm_symbols import is_at_least

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

def required_runtime_artifacts(upstream_tag: str) -> list[Path]:
    required = list(REQUIRED_RUNTIME_ARTIFACTS)
    if is_at_least(upstream_tag, (0, 14, 0)):
        required.extend(
            Path("dist") / "official" / upstream_tag / archive
            for archive in (
                "CLiteRTLM.xcframework.zip",
                "CLiteRTLM_mac.xcframework.zip",
            )
        )
    return required


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that release packaging contains upstream runtime libraries."
    )
    parser.add_argument("--upstream-tag", required=True)
    args = parser.parse_args()

    required = required_runtime_artifacts(args.upstream_tag)
    if not is_at_least(args.upstream_tag, (0, 14, 0)):
        required.extend(
            [
                Path("dist")
                / "official"
                / args.upstream_tag
                / "CLiteRTLM.xcframework.zip",
                Path("dist")
                / "official"
                / args.upstream_tag
                / "CLiteRTLM_mac.xcframework.zip",
            ]
        )

    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    if missing:
        formatted = "\n".join(f"- {path.as_posix()}" for path in missing)
        raise SystemExit(f"Missing required runtime artifacts:\n{formatted}")

    print(f"Validated {len(required)} required runtime artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
