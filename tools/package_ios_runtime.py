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

IOS_ARCH_ORDER = {"arm64": 0, "arm64-sim": 1, "x64-sim": 2}
REQUIRED_IOS_ARCHES = {"arm64", "arm64-sim"}
XCFRAMEWORK_ARCH_TO_RUNTIME_ARCH = {
    "arm64": "arm64",
    "x86_64": "x64",
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


def discover_ios_slices(extracted_root: Path) -> list[dict]:
    xcframework_root = extracted_root / "CLiteRTLM.xcframework"
    info_plist = xcframework_root / "Info.plist"
    if not info_plist.is_file():
        raise RuntimeError(f"Missing CLiteRTLM.xcframework Info.plist: {info_plist}")

    metadata = plistlib.loads(info_plist.read_bytes())
    specs: list[dict] = []
    for library in metadata.get("AvailableLibraries", []):
        if library.get("SupportedPlatform") != "ios":
            continue
        library_identifier = library.get("LibraryIdentifier")
        library_path = library.get("LibraryPath")
        if not library_identifier or not library_path:
            continue

        source_framework_dir = xcframework_root / library_identifier / library_path
        source = source_framework_dir / "CLiteRTLM"
        source_arches = library.get("SupportedArchitectures", [])
        variant = library.get("SupportedPlatformVariant")
        if variant not in (None, "simulator"):
            continue
        for source_arch in source_arches:
            runtime_arch = XCFRAMEWORK_ARCH_TO_RUNTIME_ARCH.get(source_arch)
            if runtime_arch is None:
                continue
            if variant is None and runtime_arch != "arm64":
                continue
            arch = f"{runtime_arch}-sim" if variant == "simulator" else runtime_arch
            specs.append(
                {
                    "arch": arch,
                    "framework_binary": source,
                    "thin_arch": source_arch if len(source_arches) > 1 else None,
                    "sdk": (
                        "iphonesimulator"
                        if variant == "simulator"
                        else "iphoneos"
                    ),
                    "target_arch": source_arch,
                }
            )

    found = {spec["arch"] for spec in specs}
    missing = sorted(REQUIRED_IOS_ARCHES - found)
    if missing:
        raise RuntimeError(
            "Missing required CLiteRTLM iOS slices: " + ", ".join(missing)
        )
    return sorted(specs, key=lambda spec: IOS_ARCH_ORDER.get(spec["arch"], 99))


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


def stage_slice(spec: dict, clean: bool) -> Path:
    arch = spec["arch"]
    source = spec["framework_binary"]
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
        specs = discover_ios_slices(temp_dir)
        if clean:
            for arch in IOS_ARCH_ORDER:
                target_dir = BIN_DIR / "ios" / arch
                if target_dir.exists():
                    shutil.rmtree(target_dir)
        return [stage_slice(spec, clean=clean) for spec in specs]


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
