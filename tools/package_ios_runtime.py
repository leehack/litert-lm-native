#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
DIST_OFFICIAL_DIR = REPO_ROOT / "dist" / "official"

REQUIRED_C_API_SYMBOLS = [
    b"litert_lm_engine_settings_create",
    b"litert_lm_engine_create",
    b"litert_lm_conversation_create",
    b"litert_lm_conversation_send_message_stream",
]


IOS_FRAMEWORK_SLICES = {
    "arm64": {
        "framework_binary": Path(
            "CLiteRTLM.xcframework/ios-arm64/CLiteRTLM.framework/CLiteRTLM"
        ),
        "thin_arch": None,
    },
    "arm64-sim": {
        "framework_binary": Path(
            "CLiteRTLM.xcframework/ios-arm64_x86_64-simulator/"
            "CLiteRTLM.framework/CLiteRTLM"
        ),
        "thin_arch": "arm64",
    },
    "x64-sim": {
        "framework_binary": Path(
            "CLiteRTLM.xcframework/ios-arm64_x86_64-simulator/"
            "CLiteRTLM.framework/CLiteRTLM"
        ),
        "thin_arch": "x86_64",
    },
}


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def validate_exported_symbols(output: Path) -> None:
    data = output.read_bytes()
    missing = [
        symbol.decode("ascii")
        for symbol in REQUIRED_C_API_SYMBOLS
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRT-LM C API symbols: "
            + ", ".join(missing)
        )
    print(f"Validated LiteRT-LM C API symbols in {output}", flush=True)


def stage_slice(extracted_root: Path, arch: str, clean: bool) -> Path:
    spec = IOS_FRAMEWORK_SLICES[arch]
    source = extracted_root / spec["framework_binary"]
    if not source.is_file():
        raise RuntimeError(f"Missing CLiteRTLM framework binary: {source}")

    target_dir = BIN_DIR / "ios" / arch
    if clean and target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    output = target_dir / "libLiteRtLm.dylib"
    thin_arch = spec["thin_arch"]
    if thin_arch:
        run(["lipo", str(source), "-thin", thin_arch, "-output", str(output)])
    else:
        shutil.copy2(source, output)

    run(["install_name_tool", "-id", "@rpath/libLiteRtLm.dylib", str(output)])
    validate_exported_symbols(output)
    print(f"Staged {output}", flush=True)
    return output


def package_ios_runtime(archive: Path, clean: bool) -> list[Path]:
    if not archive.is_file():
        raise RuntimeError(f"Missing upstream iOS xcframework archive: {archive}")

    with tempfile.TemporaryDirectory(prefix="litert-lm-native-ios-") as temp:
        temp_dir = Path(temp)
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(temp_dir)
        return [
            stage_slice(temp_dir, arch, clean=clean)
            for arch in IOS_FRAMEWORK_SLICES
        ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Package official upstream CLiteRTLM.xcframework slices as "
            "dylib-style iOS runtime payloads."
        )
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument(
        "--archive",
        type=Path,
        help=(
            "Path to CLiteRTLM.xcframework.zip. Defaults to "
            "dist/official/<tag>/CLiteRTLM.xcframework.zip."
        ),
    )
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    archive = args.archive or (
        DIST_OFFICIAL_DIR / args.upstream_tag / "CLiteRTLM.xcframework.zip"
    )
    staged = package_ios_runtime(archive.resolve(), clean=args.clean)
    print(f"Packaged {len(staged)} iOS LiteRT-LM runtime slices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
