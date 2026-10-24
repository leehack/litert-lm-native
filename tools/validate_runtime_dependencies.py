#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from ios_runtime_policy import provider_free_ios, validate_ios_directory, validate_ios_archives
from ios_framework_metadata import validate_framework_metadata
from runtime_dependency_utils import (
    elf_exported_symbols,
    elf_has_global_flag,
    elf_load_alignments,
    elf_needed_libraries,
    is_elf,
    is_system_needed,
)
from litert_lm_symbols import (
    ANDROID_OPENCL_SAMPLER_SYMBOLS,
    APPLE_METAL_ACCELERATOR_SYMBOLS,
    APPLE_METAL_SAMPLER_SYMBOLS,
)
from macos_runtime_policy import (
    UNSUPPORTED_MACOS_ARCH_REASON,
    unresolved_provider_symbols,
    unsupported_macos_runtime_dirs,
    validate_macos_archives,
)
import windows_runtime

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID_MIN_LOAD_ALIGNMENT = 0x4000


def fail(message: str) -> None:
    raise SystemExit(message)


def iter_elf_libraries(root: Path) -> list[Path]:
    bin_dir = root / "bin"
    if not bin_dir.exists():
        return []
    return sorted(
        path for path in bin_dir.rglob("*.so") if path.is_file() and is_elf(path)
    )


def platform_for(path: Path, root: Path) -> str | None:
    relative = path.relative_to(root)
    parts = relative.parts
    if len(parts) < 4 or parts[0] != "bin":
        return None
    return parts[1]


def validate_elf_dependencies(root: Path) -> int:
    checked = 0
    errors: list[str] = []
    for library in iter_elf_libraries(root):
        platform = platform_for(library, root)
        if platform is None:
            continue
        checked += 1
        for needed in elf_needed_libraries(library):
            if is_system_needed(platform, needed):
                continue
            dependency_path = library.parent / needed
            if not dependency_path.is_file():
                errors.append(
                    f"{library.relative_to(root).as_posix()} needs {needed}, "
                    "but it is missing from the same runtime directory."
                )
        if platform == "android":
            bad_alignments = [
                alignment
                for alignment in elf_load_alignments(library)
                if alignment < ANDROID_MIN_LOAD_ALIGNMENT
            ]
            if bad_alignments:
                formatted = ", ".join(hex(value) for value in bad_alignments)
                errors.append(
                    f"{library.relative_to(root).as_posix()} has Android LOAD "
                    f"alignment below 16 KB: {formatted}"
                )
            if (
                library.name == "libLiteRtLm.so"
                and not elf_has_global_flag(library)
            ):
                errors.append(
                    f"{library.relative_to(root).as_posix()} is missing the "
                    "ELF DF_1_GLOBAL flag required by dlopened LiteRT GPU "
                    "sampler plugins."
                )
            if library.name == "libLiteRtTopKOpenClSampler.so":
                exported = elf_exported_symbols(library)
                missing = sorted(set(ANDROID_OPENCL_SAMPLER_SYMBOLS) - exported)
                if missing:
                    errors.append(
                        f"{library.relative_to(root).as_posix()} is missing "
                        "required OpenCL sampler exports: "
                        + ", ".join(missing)
                    )

    if errors:
        fail(
            "Runtime dependency validation failed:\n"
            + "\n".join(f"- {e}" for e in errors)
        )
    return checked


def iter_macho_libraries(root: Path) -> list[Path]:
    bin_dir = root / "bin"
    if not bin_dir.exists():
        return []
    libraries = {
        path
        for platform in ("ios", "macos")
        for path in (bin_dir / platform).rglob("*.dylib")
        if path.is_file()
    }
    for platform in ("ios", "macos"):
        platform_dir = bin_dir / platform
        if not platform_dir.is_dir():
            continue
        for framework in platform_dir.rglob("*.framework"):
            binary = framework / framework.stem
            if binary.is_file():
                libraries.add(binary)
    if libraries:
        missing_tools = [tool for tool in ("otool", "nm") if shutil.which(tool) is None]
        if missing_tools:
            raise RuntimeError(
                "Apple runtime validation requires " + ", ".join(missing_tools)
                + "; install/select the Xcode command-line tools before qualifying Apple artifacts."
            )
    return sorted(libraries)


def macho_needed_libraries(path: Path) -> list[str]:
    result = subprocess.run(
        ["otool", "-L", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    libraries: list[str] = []
    for line in result.stdout.splitlines():
        if not line[:1].isspace():
            continue
        stripped = line.strip()
        if not stripped:
            continue
        library = stripped.split(" ", 1)[0]
        if library not in libraries:
            libraries.append(library)
    return libraries


def is_system_macho_needed(install_name: str) -> bool:
    return (
        install_name.startswith("/System/Library/")
        or install_name.startswith("/usr/lib/")
        or install_name == Path(install_name).name
    )


def runtime_dir_for_macho(path: Path, root: Path) -> Path | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 3 or parts[0] != "bin":
        return None
    return root / parts[0] / parts[1] / parts[2]


def resolve_macho_dependency(
    library: Path,
    install_name: str,
    root: Path,
) -> Path | None:
    if install_name.startswith("@loader_path/"):
        return library.parent / install_name.removeprefix("@loader_path/")

    if not install_name.startswith("@rpath/"):
        return library.parent / Path(install_name).name

    runtime_dir = runtime_dir_for_macho(library, root)
    if runtime_dir is None:
        return None
    relative = install_name.removeprefix("@rpath/")
    if ".framework/" in relative:
        return runtime_dir / relative
    return runtime_dir / Path(relative).name


def macho_exported_symbols(path: Path) -> set[str]:
    if shutil.which("nm") is None:
        return set()
    result = subprocess.run(
        ["nm", "-gU", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    symbols: set[str] = set()
    for line in result.stdout.splitlines():
        symbol = line.rsplit(maxsplit=1)[-1] if line.strip() else ""
        if symbol.startswith("_"):
            symbol = symbol[1:]
        if symbol:
            symbols.add(symbol)
    return symbols


def validate_macho_dependencies(root: Path) -> int:
    checked = 0
    errors: list[str] = [
        f"{path.relative_to(root).as_posix()} is not a supported runtime "
        f"directory: {UNSUPPORTED_MACOS_ARCH_REASON}."
        for path in unsupported_macos_runtime_dirs(root / "bin" / "macos")
    ]
    for library in iter_macho_libraries(root):
        checked += 1
        relative = library.relative_to(root)
        if relative.parts[:2] == ("bin", "ios") and library.parent.suffix == ".framework":
            platform = "iPhoneSimulator" if relative.parts[2].endswith("-sim") else "iPhoneOS"
            validate_framework_metadata(library.parent, platform)
        for needed in macho_needed_libraries(library):
            if is_system_macho_needed(needed):
                continue
            dependency_path = resolve_macho_dependency(library, needed, root)
            if dependency_path is None or not dependency_path.is_file():
                errors.append(
                    f"{library.relative_to(root).as_posix()} needs {needed}, "
                    "but it is missing from the runtime directory."
                )

        for arch, unresolved in unresolved_provider_symbols(library).items():
            errors.append(
                f"{library.relative_to(root).as_posix()} ({arch}) leaves required "
                "Gemma constraint provider symbols unresolved: "
                + ", ".join(unresolved)
            )

        required_exports: set[str] = set()
        if library.name == "LiteRtMetalAccelerator":
            required_exports.update(APPLE_METAL_ACCELERATOR_SYMBOLS)
        elif library.name == "LiteRtTopKMetalSampler":
            required_exports.update(APPLE_METAL_SAMPLER_SYMBOLS)
        if required_exports:
            missing = sorted(required_exports - macho_exported_symbols(library))
            if missing:
                errors.append(
                    f"{library.relative_to(root).as_posix()} is missing required "
                    "Metal plugin exports: " + ", ".join(missing)
                )

    if errors:
        fail(
            "Runtime dependency validation failed:\n"
            + "\n".join(f"- {e}" for e in errors)
        )
    return checked


def validate_pe_dependencies(root: Path) -> int:
    """Every Windows bundle must load on a host without the Visual C++ redistributable."""
    windows_dir = root / "bin" / "windows"
    if not windows_dir.is_dir():
        return 0
    checked = 0
    errors: list[str] = []
    for runtime_dir in sorted(path for path in windows_dir.iterdir() if path.is_dir()):
        prefix = runtime_dir.relative_to(root).as_posix()
        try:
            images = windows_runtime.read_bundle(runtime_dir)
        except windows_runtime.PeError as error:
            errors.append(f"{prefix}/{error}")
            continue
        checked += len(images)
        errors.extend(
            f"{prefix}/{error}"
            for error in windows_runtime.bundle_errors(images, runtime_dir.name)
        )
    if errors:
        fail(
            "Runtime dependency validation failed:\n"
            + "\n".join(f"- {e}" for e in errors)
        )
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that packaged native runtimes include non-system ELF, "
            "Mach-O and PE dependencies and Android libraries are 16 KB "
            "page-size compatible."
        )
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--upstream-tag", required=True, help="Selected upstream API compatibility tag.")
    parser.add_argument("--archive-root", type=Path, help="Produced archive directory; preserved official inputs are excluded.")
    args = parser.parse_args()

    root = args.root.resolve()
    if provider_free_ios(args.upstream_tag):
        validate_ios_directory(root / "bin" / "ios")
        validate_ios_archives(args.archive_root or root / "dist" / "spm")
    checked_elf = validate_elf_dependencies(root)
    checked_macho = validate_macho_dependencies(root)
    checked_pe = validate_pe_dependencies(root)
    macos_archive_errors = validate_macos_archives(args.archive_root or root / "dist" / "spm")
    if macos_archive_errors:
        fail(
            "macOS archive validation failed:\n"
            + "\n".join(f"- {e}" for e in macos_archive_errors)
        )
    print(
        "Validated runtime dependencies for "
        f"{checked_elf} ELF libraries, {checked_macho} Mach-O libraries "
        f"and {checked_pe} Windows DLLs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
