#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_RUNTIME_ARTIFACTS = [
    Path("bin/android/arm64/libLiteRtLm.so"),
    Path("bin/android/x64/libLiteRtLm.so"),
    Path("bin/ios/arm64/LiteRtLm.framework/LiteRtLm"),
    Path("bin/ios/arm64/CLiteRTLM.framework/CLiteRTLM"),
    Path("bin/ios/arm64-sim/LiteRtLm.framework/LiteRtLm"),
    Path("bin/ios/arm64-sim/CLiteRTLM.framework/CLiteRTLM"),
    Path("bin/ios/x64-sim/LiteRtLm.framework/LiteRtLm"),
    Path("bin/ios/x64-sim/CLiteRTLM.framework/CLiteRTLM"),
    Path("bin/linux/arm64/libLiteRtLm.so"),
    Path("bin/linux/x64/libLiteRtLm.so"),
    Path("bin/macos/arm64/libLiteRtLm.dylib"),
    Path("bin/macos/x64/libLiteRtLm.dylib"),
    Path("bin/windows/x64/LiteRtLm.dll"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that release packaging contains upstream runtime libraries."
    )
    parser.add_argument("--upstream-tag", required=True)
    args = parser.parse_args()

    required = list(REQUIRED_RUNTIME_ARTIFACTS)
    required.append(
        Path("dist") / "official" / args.upstream_tag / "CLiteRTLM.xcframework.zip"
    )

    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    if missing:
        formatted = "\n".join(f"- {path.as_posix()}" for path in missing)
        raise SystemExit(f"Missing required runtime artifacts:\n{formatted}")

    print(f"Validated {len(required)} required runtime artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
