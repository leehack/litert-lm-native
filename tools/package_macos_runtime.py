#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
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
DEFAULT_MACOS_MINIMUM_OS = "14.0"

REQUIRED_PROVIDER_SYMBOLS = [
    b"LiteRtLmGemmaModelConstraintProvider_Create",
    b"LiteRtLmGemmaModelConstraintProvider_CreateConstraintFromTools",
    b"LiteRtLmGemmaModelConstraintProvider_Destroy",
]

LITERTLM_LIBRARY = "libLiteRtLm.dylib"
CLITERTLM_MAC_LIBRARY = "libCLiteRTLM_mac.dylib"
LITERTLM_INSTALL_NAME = f"@rpath/{LITERTLM_LIBRARY}"
CLITERTLM_MAC_INSTALL_NAME = f"@rpath/{CLITERTLM_MAC_LIBRARY}"
LITERTLM_REEXPORT_NAME = LITERTLM_INSTALL_NAME.encode("ascii")
CLITERTLM_MAC_REEXPORT_NAME = CLITERTLM_MAC_INSTALL_NAME.encode("ascii")

MACOS_ARCH_ORDER = {"arm64": 0, "x64": 1}
REQUIRED_MACOS_ARCHES = set(MACOS_ARCH_ORDER)
XCFRAMEWORK_ARCH_TO_RUNTIME_ARCH = {
    "arm64": "arm64",
    "x86_64": "x64",
}
RUNTIME_ARCH_TO_MACHO_ARCH = {
    "arm64": "arm64",
    "x64": "x86_64",
}


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def validate_exported_symbols(output: Path) -> None:
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
    if CLITERTLM_MAC_REEXPORT_NAME not in data:
        raise RuntimeError(
            f"{output} does not re-export "
            f"{CLITERTLM_MAC_REEXPORT_NAME.decode('ascii')}"
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
    required_symbols = required_c_api_symbols(upstream_tag) + REQUIRED_PROVIDER_SYMBOLS
    missing = [
        symbol.decode("ascii")
        for symbol in required_symbols
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRT-LM macOS symbols: "
            + ", ".join(missing)
        )
    print(f"Validated upstream LiteRT-LM macOS symbols in {output}", flush=True)


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
    print(f"Validated source-built LiteRtLm macOS symbols in {output}", flush=True)


def discover_macos_slices(extracted_root: Path) -> list[dict]:
    xcframework_root = extracted_root / "CLiteRTLM_mac.xcframework"
    info_plist = xcframework_root / "Info.plist"
    if not info_plist.is_file():
        raise RuntimeError(
            f"Missing CLiteRTLM_mac.xcframework Info.plist: {info_plist}"
        )

    metadata = plistlib.loads(info_plist.read_bytes())
    specs: list[dict] = []
    for library in metadata.get("AvailableLibraries", []):
        if library.get("SupportedPlatform") != "macos":
            continue
        library_identifier = library.get("LibraryIdentifier")
        library_path = library.get("LibraryPath")
        if not library_identifier or not library_path:
            continue

        source = xcframework_root / library_identifier / library_path
        source_arches = library.get("SupportedArchitectures", [])
        for source_arch in source_arches:
            runtime_arch = XCFRAMEWORK_ARCH_TO_RUNTIME_ARCH.get(source_arch)
            if runtime_arch is None:
                continue
            specs.append(
                {
                    "arch": runtime_arch,
                    "source": source,
                    "source_arch": source_arch,
                }
            )

    found = {spec["arch"] for spec in specs}
    missing = sorted(REQUIRED_MACOS_ARCHES - found)
    if missing:
        raise RuntimeError(
            "Missing required CLiteRTLM_mac macOS slices: " + ", ".join(missing)
        )
    return sorted(specs, key=lambda spec: MACOS_ARCH_ORDER.get(spec["arch"], 99))


def create_universal_upstream(
    specs: list[dict],
    work_dir: Path,
    upstream_tag: str,
) -> Path:
    slices: list[Path] = []
    for spec in specs:
        source = spec["source"]
        if not source.is_file():
            raise RuntimeError(f"Missing CLiteRTLM_mac binary: {source}")
        thin_output = work_dir / f"{spec['arch']}-{CLITERTLM_MAC_LIBRARY}"
        run(
            [
                "lipo",
                str(source),
                "-thin",
                spec["source_arch"],
                "-output",
                str(thin_output),
            ]
        )
        slices.append(thin_output)

    upstream = work_dir / CLITERTLM_MAC_LIBRARY
    if len(slices) == 1:
        shutil.copy2(slices[0], upstream)
    else:
        run(
            [
                "xcrun",
                "lipo",
                "-create",
                *[str(path) for path in slices],
                "-output",
                str(upstream),
            ]
        )
    run(["install_name_tool", "-id", CLITERTLM_MAC_INSTALL_NAME, str(upstream)])
    validate_upstream_symbols(upstream, upstream_tag)
    return upstream


def build_wrapper(upstream: Path, work_dir: Path, target_arches: list[str]) -> Path:
    output = work_dir / LITERTLM_LIBRARY
    arch_args: list[str] = []
    for target_arch in target_arches:
        arch_args.extend(["-arch", target_arch])

    run(
        [
            "xcrun",
            "clang",
            "-dynamiclib",
            "-O2",
            "-std=c11",
            "-fvisibility=hidden",
            *arch_args,
            f"-mmacosx-version-min={DEFAULT_MACOS_MINIMUM_OS}",
            "-install_name",
            LITERTLM_INSTALL_NAME,
            "-Wl,-rpath,@loader_path",
            "-Wl,-reexport_library," + str(upstream),
            "-o",
            str(output),
            str(BRIDGE_SOURCE),
        ]
    )
    validate_exported_symbols(output)
    return output


def thin_to_runtime_arch(source: Path, arch: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "lipo",
            str(source),
            "-thin",
            RUNTIME_ARCH_TO_MACHO_ARCH[arch],
            "-output",
            str(destination),
        ]
    )


def stage_runtime(
    upstream: Path,
    wrapper: Path,
    specs: list[dict],
    clean: bool,
) -> list[Path]:
    staged: list[Path] = []
    for spec in specs:
        arch = spec["arch"]
        target_dir = BIN_DIR / "macos" / arch
        if clean and target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        wrapper_output = target_dir / LITERTLM_LIBRARY
        upstream_output = target_dir / CLITERTLM_MAC_LIBRARY
        thin_to_runtime_arch(wrapper, arch, wrapper_output)
        thin_to_runtime_arch(upstream, arch, upstream_output)
        staged.extend([wrapper_output, upstream_output])
        print(f"Staged {wrapper_output}", flush=True)
        print(f"Staged {upstream_output}", flush=True)
    return staged


def discover_source_built_macos_slices() -> list[dict]:
    specs: list[dict] = []
    for arch in MACOS_ARCH_ORDER:
        source = BIN_DIR / "macos" / arch / LITERTLM_LIBRARY
        if not source.is_file():
            continue
        specs.append(
            {
                "arch": arch,
                "source": source,
                "source_arch": RUNTIME_ARCH_TO_MACHO_ARCH[arch],
            }
        )

    found = {spec["arch"] for spec in specs}
    missing = sorted(REQUIRED_MACOS_ARCHES - found)
    if missing:
        raise RuntimeError(
            "Missing source-built LiteRtLm macOS slices: " + ", ".join(missing)
        )
    return sorted(specs, key=lambda spec: MACOS_ARCH_ORDER.get(spec["arch"], 99))


def build_source_reexport_wrapper(spec: dict, source: Path, output: Path) -> None:
    output.unlink(missing_ok=True)
    run(
        [
            "xcrun",
            "clang",
            "-dynamiclib",
            "-O2",
            "-std=c11",
            "-fvisibility=hidden",
            "-arch",
            spec["source_arch"],
            f"-mmacosx-version-min={DEFAULT_MACOS_MINIMUM_OS}",
            "-install_name",
            CLITERTLM_MAC_INSTALL_NAME,
            "-Wl,-rpath,@loader_path",
            "-Wl,-reexport_library," + str(source),
            "-o",
            str(output),
            "-x",
            "c",
            "/dev/null",
        ]
    )
    validate_reexport_symbols(output, LITERTLM_REEXPORT_NAME)


def stage_source_built_runtime(
    specs: list[dict],
    clean: bool,
    upstream_tag: str,
) -> list[Path]:
    staged: list[Path] = []
    for spec in specs:
        arch = spec["arch"]
        source = spec["source"]
        target_dir = BIN_DIR / "macos" / arch
        if clean:
            (target_dir / CLITERTLM_MAC_LIBRARY).unlink(missing_ok=True)
        run(["install_name_tool", "-id", LITERTLM_INSTALL_NAME, str(source)])
        validate_source_built_symbols(source, upstream_tag)
        companion = target_dir / CLITERTLM_MAC_LIBRARY
        build_source_reexport_wrapper(spec, source, companion)
        staged.extend([source, companion])
        print(f"Staged {source}", flush=True)
        print(f"Staged {companion}", flush=True)
    return staged


def package_macos_runtime(
    archive: Path,
    clean: bool,
    upstream_tag: str,
) -> list[Path]:
    if not archive.is_file():
        print(
            f"Missing upstream macOS xcframework archive: {archive}; "
            "using source-built LiteRtLm dylibs",
            flush=True,
        )
        specs = discover_source_built_macos_slices()
        return stage_source_built_runtime(
            specs,
            clean=clean,
            upstream_tag=upstream_tag,
        )

    with tempfile.TemporaryDirectory(prefix="litert-lm-native-macos-") as temp:
        temp_dir = Path(temp)
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(temp_dir)
        specs = discover_macos_slices(temp_dir)
        upstream = create_universal_upstream(specs, temp_dir, upstream_tag)
        target_arches = [RUNTIME_ARCH_TO_MACHO_ARCH[spec["arch"]] for spec in specs]
        wrapper = build_wrapper(upstream, temp_dir, target_arches)
        if clean:
            for arch in MACOS_ARCH_ORDER:
                target_dir = BIN_DIR / "macos" / arch
                if target_dir.exists():
                    shutil.rmtree(target_dir)
        return stage_runtime(upstream, wrapper, specs, clean=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Package official upstream CLiteRTLM_mac.xcframework slices as "
            "bridge-enabled macOS runtime dylibs."
        )
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument(
        "--archive",
        type=Path,
        help=(
            "Path to CLiteRTLM_mac.xcframework.zip. Defaults to "
            "dist/official/<tag>/CLiteRTLM_mac.xcframework.zip."
        ),
    )
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    archive = args.archive or (
        DIST_OFFICIAL_DIR / args.upstream_tag / "CLiteRTLM_mac.xcframework.zip"
    )
    staged = package_macos_runtime(
        archive.resolve(),
        clean=args.clean,
        upstream_tag=args.upstream_tag,
    )
    print(f"Packaged {len(staged)} macOS LiteRT-LM runtime files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
