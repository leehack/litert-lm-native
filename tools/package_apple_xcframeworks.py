#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
DIST_DIR = REPO_ROOT / "dist" / "spm"
WORK_DIR = REPO_ROOT / ".dart_tool" / "apple_xcframeworks"

IOS_ARCHES = ["arm64", "arm64-sim", "x64-sim"]
MACOS_ARCHES = ["arm64", "x64"]
PRIMARY_MODULE = "LiteRtLm"
IOS_REEXPORT_MODULE = "CLiteRTLM"
PRIMARY_LIBRARY = "libLiteRtLm.dylib"
IOS_PRIMARY_MODULES = {PRIMARY_MODULE, IOS_REEXPORT_MODULE}


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


def ensure_module_headers(
    headers_dir: Path,
    module_name: str,
    *,
    framework: bool = False,
) -> None:
    headers_dir.mkdir(parents=True, exist_ok=True)
    (headers_dir / f"{module_name}.h").write_text(
        "\n".join(["#pragma once", "", ""]),
        encoding="utf-8",
    )
    module_declaration = "framework module" if framework else "module"
    (headers_dir / "module.modulemap").write_text(
        "\n".join(
            [
                f"{module_declaration} {module_name} {{",
                f'  umbrella header "{module_name}.h"',
                "  export *",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def prepare_framework(source: Path, destination: Path, module_name: str) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    ensure_module_headers(destination / "Headers", module_name, framework=True)
    modules_dir = destination / "Modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        destination / "Headers" / "module.modulemap",
        modules_dir / "module.modulemap",
    )
    return destination


def existing_ios_frameworks(module_name: str) -> dict[str, Path]:
    frameworks: dict[str, Path] = {}
    for arch in IOS_ARCHES:
        framework = BIN_DIR / "ios" / arch / f"{module_name}.framework"
        binary = framework / module_name
        if binary.is_file():
            frameworks[arch] = framework
    return frameworks


def ios_framework_module_names() -> list[str]:
    modules: set[str] = set()
    for arch in IOS_ARCHES:
        arch_dir = BIN_DIR / "ios" / arch
        if not arch_dir.is_dir():
            continue
        for framework in arch_dir.glob("*.framework"):
            module_name = framework.stem
            if (framework / module_name).is_file():
                modules.add(module_name)
    return sorted(modules)


def merge_simulator_frameworks(
    frameworks: dict[str, Path],
    module_name: str,
    work_root: Path,
) -> Path | None:
    sim_frameworks = [
        (arch, framework)
        for arch, framework in frameworks.items()
        if arch.endswith("-sim")
    ]
    if not sim_frameworks:
        return None

    base_arch, base_framework = sim_frameworks[0]
    output = prepare_framework(
        base_framework,
        work_root / f"{module_name}-{base_arch}-universal" / f"{module_name}.framework",
        module_name,
    )
    if len(sim_frameworks) == 1:
        return output

    run(
        [
            "xcrun",
            "lipo",
            "-create",
            *[str(framework / module_name) for _, framework in sim_frameworks],
            "-output",
            str(output / module_name),
        ]
    )
    return output


def zip_xcframework(xcframework: Path, output_zip: Path) -> None:
    if output_zip.exists():
        output_zip.unlink()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(xcframework.rglob("*")):
            relative_path = path.relative_to(xcframework.parent)
            if path.is_symlink():
                info = zipfile.ZipInfo(relative_path.as_posix())
                info.create_system = 3
                info.external_attr = 0o120777 << 16
                archive.writestr(info, os.readlink(path))
                continue
            if path.is_dir():
                continue
            archive.write(path, relative_path)


def create_xcframework(
    module_name: str,
    args: list[str],
    work_root: Path,
    output_dir: Path,
    tag: str,
) -> Path:
    xcframework = work_root / f"{module_name}.xcframework"
    if xcframework.exists():
        shutil.rmtree(xcframework)
    run(["xcodebuild", "-create-xcframework", *args, "-output", str(xcframework)])
    output_zip = output_dir / f"litert-lm-native-apple-{module_name}-xcframework-{tag}.zip"
    zip_xcframework(xcframework, output_zip)
    print(f"Wrote {output_zip}", flush=True)
    return output_zip


def package_ios_framework_module(
    module_name: str,
    work_root: Path,
    output_dir: Path,
    tag: str,
    extra_args: list[str] | None = None,
) -> Path | None:
    frameworks = existing_ios_frameworks(module_name)
    if "arm64" not in frameworks:
        return None

    args: list[str] = []
    device = prepare_framework(
        frameworks["arm64"],
        work_root / f"{module_name}-ios-arm64" / f"{module_name}.framework",
        module_name,
    )
    args.extend(["-framework", str(device)])
    simulator = merge_simulator_frameworks(frameworks, module_name, work_root)
    if simulator is not None:
        args.extend(["-framework", str(simulator)])
    if extra_args:
        args.extend(extra_args)
    return create_xcframework(module_name, args, work_root, output_dir, tag)


def macos_libraries_by_name() -> dict[str, dict[str, Path]]:
    libraries: dict[str, dict[str, Path]] = {}
    for arch in MACOS_ARCHES:
        arch_dir = BIN_DIR / "macos" / arch
        if not arch_dir.is_dir():
            continue
        for path in sorted(arch_dir.glob("*.dylib")):
            libraries.setdefault(path.name, {})[arch] = path
    return libraries


def make_macos_library_argument(
    module_name: str,
    libraries: dict[str, Path],
    work_root: Path,
    *,
    include_headers: bool = True,
) -> list[str]:
    if not libraries:
        return []
    output_dir = work_root / f"{module_name}-macos"
    output_dir.mkdir(parents=True, exist_ok=True)

    if len(libraries) == 1:
        library = next(iter(libraries.values()))
    else:
        library = output_dir / next(iter(libraries.values())).name
        run(
            [
                "xcrun",
                "lipo",
                "-create",
                *[str(libraries[arch]) for arch in sorted(libraries)],
                "-output",
                str(library),
            ]
        )
    if not include_headers:
        return ["-library", str(library)]

    headers_dir = output_dir / "Headers"
    ensure_module_headers(headers_dir, module_name)
    return ["-library", str(library), "-headers", str(headers_dir)]


def make_macos_framework_argument(
    module_name: str,
    libraries: dict[str, Path],
    work_root: Path,
) -> list[str]:
    library_args = make_macos_library_argument(module_name, libraries, work_root)
    if not library_args:
        return []
    library = Path(library_args[1])
    framework = work_root / f"{module_name}-macos-framework" / f"{module_name}.framework"
    if framework.exists():
        shutil.rmtree(framework)

    version_dir = framework / "Versions" / "A"
    headers_dir = version_dir / "Headers"
    modules_dir = version_dir / "Modules"
    resources_dir = version_dir / "Resources"
    headers_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)
    ensure_module_headers(headers_dir, module_name, framework=True)
    shutil.copy2(headers_dir / "module.modulemap", modules_dir / "module.modulemap")

    binary = version_dir / module_name
    shutil.copy2(library, binary)
    binary.chmod(0o755)
    run(
        [
            "install_name_tool",
            "-id",
            f"@rpath/{module_name}.framework/Versions/A/{module_name}",
            str(binary),
        ]
    )

    info_plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": module_name,
        "CFBundleIdentifier": f"dev.leehack.litertlm.native.{module_name}",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": module_name,
        "CFBundlePackageType": "FMWK",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
    }
    with (resources_dir / "Info.plist").open("wb") as file:
        plistlib.dump(info_plist, file)

    (framework / "Versions" / "Current").symlink_to("A")
    for name in ["Headers", "Modules", "Resources", module_name]:
        (framework / name).symlink_to(Path("Versions") / "Current" / name)
    return ["-framework", str(framework)]


def package_macos_companions(
    work_root: Path,
    output_dir: Path,
    tag: str,
    macos_args_by_module: dict[str, list[str]],
    skip_modules: set[str],
) -> list[Path]:
    packaged: list[Path] = []
    for module_name, args in sorted(macos_args_by_module.items()):
        if module_name in skip_modules:
            continue
        if args:
            packaged.append(
                create_xcframework(module_name, args, work_root, output_dir, tag)
            )
    return packaged


def macos_companion_args_by_module(
    work_root: Path,
    framework_modules: set[str],
) -> dict[str, list[str]]:
    args_by_module: dict[str, list[str]] = {}
    for library_name, libraries in sorted(macos_libraries_by_name().items()):
        if library_name == PRIMARY_LIBRARY:
            continue
        module_name = module_name_for_dylib(Path(library_name))
        if module_name in framework_modules:
            args = make_macos_framework_argument(module_name, libraries, work_root)
        else:
            args = make_macos_library_argument(
                module_name,
                libraries,
                work_root,
                include_headers=False,
            )
        if args:
            args_by_module[module_name] = args
    return args_by_module


def package_ios_companions(
    work_root: Path,
    output_dir: Path,
    tag: str,
    macos_args_by_module: dict[str, list[str]],
) -> tuple[list[Path], set[str]]:
    packaged: list[Path] = []
    packaged_modules: set[str] = set()
    for module_name in ios_framework_module_names():
        if module_name in IOS_PRIMARY_MODULES:
            continue
        companion = package_ios_framework_module(
            module_name,
            work_root,
            output_dir,
            tag,
            extra_args=macos_args_by_module.get(module_name),
        )
        if companion is not None:
            packaged.append(companion)
            packaged_modules.add(module_name)
    return packaged, packaged_modules


def package_all(release_tag: str, clean: bool) -> list[Path]:
    output_dir = DIST_DIR / release_tag
    if clean and WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    packaged: list[Path] = []
    ios_companion_modules = set(ios_framework_module_names()) - IOS_PRIMARY_MODULES
    macos_companion_args = macos_companion_args_by_module(
        WORK_DIR,
        framework_modules=ios_companion_modules,
    )
    primary_macos_args = make_macos_framework_argument(
        PRIMARY_MODULE,
        macos_libraries_by_name().get(PRIMARY_LIBRARY, {}),
        WORK_DIR,
    )
    primary = package_ios_framework_module(
        PRIMARY_MODULE,
        WORK_DIR,
        output_dir,
        release_tag,
        extra_args=primary_macos_args,
    )
    if primary is None and primary_macos_args:
        primary = create_xcframework(
            PRIMARY_MODULE,
            primary_macos_args,
            WORK_DIR,
            output_dir,
            release_tag,
        )
    if primary is None:
        raise RuntimeError("Could not package LiteRtLm: no iOS or macOS runtime found")
    packaged.append(primary)

    clitertlm = package_ios_framework_module(
        IOS_REEXPORT_MODULE,
        WORK_DIR,
        output_dir,
        release_tag,
    )
    if clitertlm is not None:
        packaged.append(clitertlm)

    ios_companions, ios_companion_modules = package_ios_companions(
        WORK_DIR,
        output_dir,
        release_tag,
        macos_companion_args,
    )
    packaged.extend(ios_companions)
    packaged.extend(
        package_macos_companions(
            WORK_DIR,
            output_dir,
            release_tag,
            macos_companion_args,
            skip_modules=ios_companion_modules,
        )
    )
    return packaged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package Apple LiteRT-LM runtimes as SPM-compatible XCFramework zips."
    )
    parser.add_argument(
        "--release-tag",
        help="Native release tag to use for output directory and asset names.",
    )
    parser.add_argument(
        "--upstream-tag",
        help="Deprecated alias for --release-tag.",
    )
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    release_tag = args.release_tag or args.upstream_tag
    if not release_tag:
        parser.error("--release-tag is required")
    packaged = package_all(release_tag, clean=args.clean)
    if not packaged:
        raise RuntimeError("No Apple XCFramework zips were produced")
    for path in packaged:
        print(path.relative_to(REPO_ROOT).as_posix(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
