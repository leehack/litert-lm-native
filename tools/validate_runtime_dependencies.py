#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from runtime_dependency_utils import (
    elf_load_alignments,
    elf_needed_libraries,
    is_elf,
    is_system_needed,
)

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
    checked = validate_elf_dependencies(root)
    print(f"Validated runtime dependencies for {checked} ELF libraries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
