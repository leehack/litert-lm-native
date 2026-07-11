#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

from runtime_dependency_utils import (
    elf_has_global_flag,
    elf_load_alignments,
    elf_needed_libraries,
    is_elf,
    is_system_needed,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID_MIN_LOAD_ALIGNMENT = 0x4000
MACOS_UNRESOLVED_PROVIDER_SYMBOLS = {
    "_LiteRtLmGemmaModelConstraintProvider_Create",
    "_LiteRtLmGemmaModelConstraintProvider_CreateConstraintFromTools",
    "_LiteRtLmGemmaModelConstraintProvider_Destroy",
}


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

    if errors:
        fail(
            "Runtime dependency validation failed:\n"
            + "\n".join(f"- {e}" for e in errors)
        )
    return checked


def iter_macho_libraries(root: Path) -> list[Path]:
    bin_dir = root / "bin"
    if not bin_dir.exists() or shutil.which("otool") is None:
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


def unresolved_dynamic_lookup_symbols(path: Path) -> list[str]:
    if shutil.which("nm") is None:
        return []
    result = subprocess.run(
        ["nm", "-m", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    symbols: list[str] = []
    for line in result.stdout.splitlines():
        if "(undefined)" not in line or "(dynamically looked up)" not in line:
            continue
        match = re.search(r"\b(_[A-Za-z0-9_]+)\s+\(dynamically looked up\)", line)
        if match:
            symbols.append(match.group(1))
    return symbols


def allows_unresolved_macos_provider_symbols(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    # The source-built v0.14.0 x64 LiteRtLm dylib leaves these optional symbols
    # as dynamic lookups and does not link a provider install name.
    return relative.parts == ("bin", "macos", "x64", "libLiteRtLm.dylib")


def validate_macho_dependencies(root: Path) -> int:
    checked = 0
    errors: list[str] = []
    for library in iter_macho_libraries(root):
        checked += 1
        for needed in macho_needed_libraries(library):
            if is_system_macho_needed(needed):
                continue
            dependency_path = resolve_macho_dependency(library, needed, root)
            if dependency_path is None or not dependency_path.is_file():
                errors.append(
                    f"{library.relative_to(root).as_posix()} needs {needed}, "
                    "but it is missing from the runtime directory."
                )

        unresolved = [
            symbol
            for symbol in unresolved_dynamic_lookup_symbols(library)
            if symbol in MACOS_UNRESOLVED_PROVIDER_SYMBOLS
        ]
        if unresolved and not allows_unresolved_macos_provider_symbols(library, root):
            formatted = ", ".join(sorted(unresolved))
            errors.append(
                f"{library.relative_to(root).as_posix()} leaves required Gemma "
                f"constraint provider symbols unresolved: {formatted}"
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
            "Validate that packaged native runtimes include non-system ELF "
            "dependencies and Android libraries are 16 KB page-size compatible."
        )
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()

    root = args.root.resolve()
    checked_elf = validate_elf_dependencies(root)
    checked_macho = validate_macho_dependencies(root)
    print(
        "Validated runtime dependencies for "
        f"{checked_elf} ELF libraries and {checked_macho} Mach-O libraries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
