#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
DIST_OFFICIAL_DIR = REPO_ROOT / "dist" / "official"
STREAM_PROXY_SOURCE = REPO_ROOT / "native" / "stream_proxy" / "stream_proxy.c"
DEFAULT_IOS_MINIMUM_OS = "15.0"

REQUIRED_C_API_SYMBOLS = [
    b"litert_lm_engine_settings_create",
    b"litert_lm_engine_create",
    b"litert_lm_conversation_create",
    b"litert_lm_conversation_send_message_stream",
]

REQUIRED_STREAM_PROXY_SYMBOLS = [
    b"stream_proxy_load_global",
    b"stream_proxy_create",
    b"stream_proxy_delete",
    b"stream_proxy_free_string",
]

LITERTLM_INSTALL_NAME = "@rpath/LiteRtLm.framework/LiteRtLm"
CLITERTLM_INSTALL_NAME = "@rpath/CLiteRTLM.framework/CLiteRTLM"
CLITERTLM_REEXPORT_NAME = CLITERTLM_INSTALL_NAME.encode("ascii")


IOS_FRAMEWORK_SLICES = {
    "arm64": {
        "framework_binary": Path(
            "CLiteRTLM.xcframework/ios-arm64/CLiteRTLM.framework/CLiteRTLM"
        ),
        "thin_arch": None,
        "sdk": "iphoneos",
        "target_arch": "arm64",
    },
    "arm64-sim": {
        "framework_binary": Path(
            "CLiteRTLM.xcframework/ios-arm64_x86_64-simulator/"
            "CLiteRTLM.framework/CLiteRTLM"
        ),
        "thin_arch": "arm64",
        "sdk": "iphonesimulator",
        "target_arch": "arm64",
    },
    "x64-sim": {
        "framework_binary": Path(
            "CLiteRTLM.xcframework/ios-arm64_x86_64-simulator/"
            "CLiteRTLM.framework/CLiteRTLM"
        ),
        "thin_arch": "x86_64",
        "sdk": "iphonesimulator",
        "target_arch": "x86_64",
    },
}


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def validate_exported_symbols(output: Path) -> None:
    data = output.read_bytes()
    missing = [
        symbol.decode("ascii")
        for symbol in REQUIRED_STREAM_PROXY_SYMBOLS
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required StreamProxy symbols: "
            + ", ".join(missing)
        )
    if CLITERTLM_REEXPORT_NAME not in data:
        raise RuntimeError(
            f"{output} does not re-export "
            f"{CLITERTLM_REEXPORT_NAME.decode('ascii')}"
        )
    print(f"Validated StreamProxy wrapper symbols in {output}", flush=True)


def validate_upstream_symbols(output: Path) -> None:
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
    print(f"Validated upstream LiteRT-LM C API symbols in {output}", flush=True)


def write_framework_info_plist(
    framework_dir: Path,
    *,
    executable: str,
    bundle_identifier: str,
    supported_platform: str,
) -> None:
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": executable,
        "CFBundleIdentifier": bundle_identifier,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": executable,
        "CFBundlePackageType": "FMWK",
        "CFBundleShortVersionString": "1.0",
        "CFBundleSupportedPlatforms": [supported_platform],
        "CFBundleVersion": "1",
        "MinimumOSVersion": DEFAULT_IOS_MINIMUM_OS,
    }
    with (framework_dir / "Info.plist").open("wb") as file:
        plistlib.dump(plist, file)


def copy_framework_info_plist(
    source_framework_dir: Path,
    target_framework_dir: Path,
) -> None:
    source_plist = source_framework_dir / "Info.plist"
    if not source_plist.is_file():
        raise RuntimeError(f"Missing framework Info.plist: {source_plist}")
    shutil.copy2(source_plist, target_framework_dir / "Info.plist")


def build_wrapper(spec: dict, framework_dir: Path, upstream: Path) -> Path:
    output = framework_dir / "LiteRtLm"
    min_version_flag = (
        f"-miphoneos-version-min={DEFAULT_IOS_MINIMUM_OS}"
        if spec["sdk"] == "iphoneos"
        else f"-mios-simulator-version-min={DEFAULT_IOS_MINIMUM_OS}"
    )
    run([
        "xcrun",
        "--sdk",
        spec["sdk"],
        "clang",
        "-dynamiclib",
        "-O2",
        "-std=c11",
        "-fvisibility=hidden",
        "-arch",
        spec["target_arch"],
        min_version_flag,
        "-install_name",
        LITERTLM_INSTALL_NAME,
        "-Wl,-reexport_library," + str(upstream),
        "-o",
        str(output),
        str(STREAM_PROXY_SOURCE),
    ])
    validate_exported_symbols(output)
    return output


def stage_slice(extracted_root: Path, arch: str, clean: bool) -> Path:
    spec = IOS_FRAMEWORK_SLICES[arch]
    source = extracted_root / spec["framework_binary"]
    if not source.is_file():
        raise RuntimeError(f"Missing CLiteRTLM framework binary: {source}")

    target_dir = BIN_DIR / "ios" / arch
    if clean and target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    supported_platform = (
        "iPhoneOS" if spec["sdk"] == "iphoneos" else "iPhoneSimulator"
    )

    upstream_framework_dir = target_dir / "CLiteRTLM.framework"
    upstream_framework_dir.mkdir(parents=True, exist_ok=True)
    upstream = upstream_framework_dir / "CLiteRTLM"
    thin_arch = spec["thin_arch"]
    if thin_arch:
        run(["lipo", str(source), "-thin", thin_arch, "-output", str(upstream)])
    else:
        shutil.copy2(source, upstream)

    run([
        "install_name_tool",
        "-id",
        CLITERTLM_INSTALL_NAME,
        str(upstream),
    ])
    validate_upstream_symbols(upstream)
    copy_framework_info_plist(source.parent, upstream_framework_dir)

    wrapper_framework_dir = target_dir / "LiteRtLm.framework"
    wrapper_framework_dir.mkdir(parents=True, exist_ok=True)
    output = build_wrapper(spec, wrapper_framework_dir, upstream)

    write_framework_info_plist(
        wrapper_framework_dir,
        executable="LiteRtLm",
        bundle_identifier="dev.leehack.litertlm.native.LiteRtLm",
        supported_platform=supported_platform,
    )
    print(f"Staged {output}", flush=True)
    print(f"Staged {upstream}", flush=True)
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
            "framework-style iOS runtime payloads."
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
