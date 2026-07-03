#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from litert_lm_symbols import BRIDGE_SYMBOLS, required_c_api_symbols

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
DIST_OFFICIAL_DIR = REPO_ROOT / "dist" / "official"
BRIDGE_SOURCE = REPO_ROOT / "native" / "bridge" / "litert_lm_bridge.c"
DEFAULT_IOS_MINIMUM_OS = "15.0"

SOURCE_BUILT_LIBRARY = "libLiteRtLm.dylib"
LITERTLM_INSTALL_NAME = "@rpath/LiteRtLm.framework/LiteRtLm"
CLITERTLM_INSTALL_NAME = "@rpath/CLiteRTLM.framework/CLiteRTLM"
LITERTLM_REEXPORT_NAME = LITERTLM_INSTALL_NAME.encode("ascii")
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


def module_name_for_dylib(path: Path) -> str:
    stem = path.name
    if stem.startswith("lib"):
        stem = stem[3:]
    if stem.endswith(".dylib"):
        stem = stem[:-6]
    parts = re.split(r"[^A-Za-z0-9]+", stem)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def framework_install_name(module_name: str) -> str:
    return f"@rpath/{module_name}.framework/{module_name}"


def macho_needed_libraries(path: Path) -> list[str]:
    result = subprocess.run(
        ["otool", "-L", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    libraries: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        libraries.append(stripped.split(" ", 1)[0])
    return libraries


def is_system_macho_needed(install_name: str) -> bool:
    return (
        install_name.startswith("/System/Library/")
        or install_name.startswith("/usr/lib/")
        or install_name == Path(install_name).name
    )


def validate_bridge_symbols(output: Path, reexport_name: bytes | None) -> None:
    data = output.read_bytes()
    missing = [
        symbol.decode("ascii")
        for symbol in BRIDGE_SYMBOLS
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRtLmBridge symbols: "
            + ", ".join(missing)
        )
    if reexport_name is not None and reexport_name not in data:
        raise RuntimeError(
            f"{output} does not re-export "
            f"{reexport_name.decode('ascii')}"
        )
    print(f"Validated LiteRtLmBridge wrapper symbols in {output}", flush=True)


def validate_reexport_symbols(output: Path, reexport_name: bytes) -> None:
    data = output.read_bytes()
    if reexport_name not in data:
        raise RuntimeError(
            f"{output} does not re-export {reexport_name.decode('ascii')}"
        )
    print(f"Validated re-export wrapper in {output}", flush=True)


def validate_upstream_symbols(output: Path, upstream_tag: str) -> None:
    data = output.read_bytes()
    missing = [
        symbol.decode("ascii")
        for symbol in required_c_api_symbols(upstream_tag)
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRT-LM C API symbols: "
            + ", ".join(missing)
        )
    print(f"Validated upstream LiteRT-LM C API symbols in {output}", flush=True)


def validate_source_built_symbols(output: Path, upstream_tag: str) -> None:
    data = output.read_bytes()
    required_symbols = required_c_api_symbols(upstream_tag) + BRIDGE_SYMBOLS
    missing = [
        symbol.decode("ascii")
        for symbol in required_symbols
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRT-LM/bridge symbols: "
            + ", ".join(missing)
        )
    print(f"Validated source-built LiteRtLm symbols in {output}", flush=True)


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


def min_version_flag(sdk: str) -> str:
    if sdk == "iphoneos":
        return f"-miphoneos-version-min={DEFAULT_IOS_MINIMUM_OS}"
    return f"-mios-simulator-version-min={DEFAULT_IOS_MINIMUM_OS}"


def build_wrapper(spec: dict, framework_dir: Path, upstream: Path) -> Path:
    output = framework_dir / "LiteRtLm"
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
        min_version_flag(spec["sdk"]),
        "-install_name",
        LITERTLM_INSTALL_NAME,
        "-Wl,-reexport_library," + str(upstream),
        "-o",
        str(output),
        str(BRIDGE_SOURCE),
    ])
    validate_bridge_symbols(output, CLITERTLM_REEXPORT_NAME)
    return output


def build_reexport_wrapper(
    spec: dict,
    framework_dir: Path,
    module_name: str,
    install_name: str,
    reexported: Path,
) -> Path:
    output = framework_dir / module_name
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
        min_version_flag(spec["sdk"]),
        "-install_name",
        install_name,
        "-Wl,-reexport_library," + str(reexported),
        "-o",
        str(output),
        "-x",
        "c",
        "/dev/null",
    ])
    return output


def clean_staged_frameworks(target_dir: Path) -> None:
    for framework_dir in target_dir.glob("*.framework"):
        if framework_dir.is_dir():
            shutil.rmtree(framework_dir)


def stage_slice(spec: dict, clean: bool, upstream_tag: str) -> Path:
    arch = spec["arch"]
    source = spec["framework_binary"]
    if not source.is_file():
        raise RuntimeError(f"Missing CLiteRTLM framework binary: {source}")

    target_dir = BIN_DIR / "ios" / arch
    target_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        clean_staged_frameworks(target_dir)
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
    validate_upstream_symbols(upstream, upstream_tag)
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


def discover_source_built_ios_slices() -> list[dict]:
    specs: list[dict] = []
    for arch in IOS_ARCH_ORDER:
        source = BIN_DIR / "ios" / arch / SOURCE_BUILT_LIBRARY
        if not source.is_file():
            continue
        simulator = arch.endswith("-sim")
        target_arch = "x86_64" if arch == "x64-sim" else "arm64"
        specs.append(
            {
                "arch": arch,
                "framework_binary": source,
                "sdk": "iphonesimulator" if simulator else "iphoneos",
                "target_arch": target_arch,
            }
        )

    found = {spec["arch"] for spec in specs}
    missing = sorted(REQUIRED_IOS_ARCHES - found)
    if missing:
        raise RuntimeError(
            "Missing source-built LiteRtLm iOS slices: " + ", ".join(missing)
        )
    return sorted(specs, key=lambda spec: IOS_ARCH_ORDER.get(spec["arch"], 99))


def stage_source_built_slice(spec: dict, clean: bool, upstream_tag: str) -> Path:
    arch = spec["arch"]
    source = spec["framework_binary"]
    target_dir = BIN_DIR / "ios" / arch
    if clean:
        clean_staged_frameworks(target_dir)
    supported_platform = (
        "iPhoneOS" if spec["sdk"] == "iphoneos" else "iPhoneSimulator"
    )

    litertlm_framework_dir = target_dir / "LiteRtLm.framework"
    litertlm_framework_dir.mkdir(parents=True, exist_ok=True)
    litertlm = litertlm_framework_dir / "LiteRtLm"
    shutil.copy2(source, litertlm)
    run(["install_name_tool", "-id", LITERTLM_INSTALL_NAME, str(litertlm)])
    stage_source_built_dependency_frameworks(spec, target_dir, litertlm)
    validate_source_built_symbols(litertlm, upstream_tag)
    write_framework_info_plist(
        litertlm_framework_dir,
        executable="LiteRtLm",
        bundle_identifier="dev.leehack.litertlm.native.LiteRtLm",
        supported_platform=supported_platform,
    )

    clitertlm_framework_dir = target_dir / "CLiteRTLM.framework"
    clitertlm_framework_dir.mkdir(parents=True, exist_ok=True)
    clitertlm = build_reexport_wrapper(
        spec,
        clitertlm_framework_dir,
        "CLiteRTLM",
        CLITERTLM_INSTALL_NAME,
        litertlm,
    )
    validate_reexport_symbols(clitertlm, LITERTLM_REEXPORT_NAME)
    write_framework_info_plist(
        clitertlm_framework_dir,
        executable="CLiteRTLM",
        bundle_identifier="dev.leehack.litertlm.native.CLiteRTLM",
        supported_platform=supported_platform,
    )

    print(f"Staged {litertlm}", flush=True)
    print(f"Staged {clitertlm}", flush=True)
    return litertlm


def stage_source_built_dependency_frameworks(
    spec: dict,
    target_dir: Path,
    litertlm: Path,
) -> None:
    for install_name in macho_needed_libraries(litertlm):
        if is_system_macho_needed(install_name):
            continue
        library_name = Path(install_name).name
        if install_name == LITERTLM_INSTALL_NAME or library_name == SOURCE_BUILT_LIBRARY:
            continue
        source = target_dir / library_name
        if not source.is_file():
            raise RuntimeError(
                f"{litertlm} depends on {install_name}, but {source} is missing"
            )
        module_name = module_name_for_dylib(source)
        framework_dir = target_dir / f"{module_name}.framework"
        framework_dir.mkdir(parents=True, exist_ok=True)
        binary = framework_dir / module_name
        shutil.copy2(source, binary)
        dependency_install_name = framework_install_name(module_name)
        run(["install_name_tool", "-id", dependency_install_name, str(binary)])
        run(
            [
                "install_name_tool",
                "-change",
                install_name,
                dependency_install_name,
                str(litertlm),
            ]
        )
        write_framework_info_plist(
            framework_dir,
            executable=module_name,
            bundle_identifier=(
                f"dev.leehack.litertlm.native.{module_name}"
            ),
            supported_platform=(
                "iPhoneOS" if spec["sdk"] == "iphoneos" else "iPhoneSimulator"
            ),
        )
        print(f"Staged {binary}", flush=True)


def package_ios_runtime(archive: Path, clean: bool, upstream_tag: str) -> list[Path]:
    if not archive.is_file():
        print(
            f"Missing upstream iOS xcframework archive: {archive}; "
            "using source-built LiteRtLm dylibs",
            flush=True,
        )
        specs = discover_source_built_ios_slices()
        return [
            stage_source_built_slice(spec, clean=clean, upstream_tag=upstream_tag)
            for spec in specs
        ]

    with tempfile.TemporaryDirectory(prefix="litert-lm-native-ios-") as temp:
        temp_dir = Path(temp)
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(temp_dir)
        specs = discover_ios_slices(temp_dir)
        if clean:
            for arch in IOS_ARCH_ORDER:
                target_dir = BIN_DIR / "ios" / arch
                if target_dir.exists():
                    clean_staged_frameworks(target_dir)
        return [
            stage_slice(spec, clean=clean, upstream_tag=upstream_tag)
            for spec in specs
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
    staged = package_ios_runtime(
        archive.resolve(),
        clean=args.clean,
        upstream_tag=args.upstream_tag,
    )
    print(f"Packaged {len(staged)} iOS LiteRT-LM runtime slices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
