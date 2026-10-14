"""macOS runtime architecture policy.

Upstream LiteRT-LM ships the Gemma model constraint provider for macOS arm64
only. A source-built x86_64 libLiteRtLm keeps the provider entry points as
non-lazy flat-namespace binds that nothing satisfies, so dyld aborts every
process that loads it, including any app that links the runtime framework
(leehack/litert-lm-native#72). macOS runtimes are published for arm64 only
until an x86_64 provider exists.
"""
from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MACOS_RUNTIME_ARCHES = ("arm64",)
MACOS_MACHO_ARCHES = ["arm64"]
UNSUPPORTED_MACOS_ARCH_REASON = (
    "macOS runtimes are published for arm64 only: upstream LiteRT-LM ships "
    "the Gemma model constraint provider for arm64 only, so an x86_64 "
    "libLiteRtLm cannot be loaded (leehack/litert-lm-native#72)"
)
PROVIDER_SYMBOLS = frozenset(
    {
        "_LiteRtLmGemmaModelConstraintProvider_Create",
        "_LiteRtLmGemmaModelConstraintProvider_CreateConstraintFromTools",
        "_LiteRtLmGemmaModelConstraintProvider_Destroy",
    }
)
MACHO_MAGIC = {
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
RUNTIME_ARCHIVE_PREFIX = "litert-lm-native-runtime-macos-"
_ARCH_HEADER = re.compile(r"\(for architecture ([A-Za-z0-9_]+)\):\s*$")
_DYNAMIC_LOOKUP = re.compile(r"\b(_[A-Za-z0-9_]+)\s+\(dynamically looked up\)")


def unsupported_macos_runtime_dirs(macos_dir: Path) -> list[Path]:
    if not macos_dir.is_dir():
        return []
    return sorted(
        path
        for path in macos_dir.iterdir()
        if path.is_dir() and path.name not in MACOS_RUNTIME_ARCHES
    )


def reject_unsupported_macos_runtime_dirs(macos_dir: Path) -> None:
    unsupported = unsupported_macos_runtime_dirs(macos_dir)
    if unsupported:
        names = ", ".join(path.name for path in unsupported)
        raise RuntimeError(
            f"Unsupported macOS runtime architecture directories in {macos_dir}: "
            f"{names}. {UNSUPPORTED_MACOS_ARCH_REASON}. Remove them before packaging."
        )


def macho_arches(binary: Path) -> list[str]:
    return subprocess.run(
        ["xcrun", "lipo", "-archs", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()


def unresolved_provider_symbols(binary: Path) -> dict[str, list[str]]:
    """Map each slice to the provider symbols it leaves to flat lookup.

    `nm` lists only the host slice of a universal binary unless asked for
    every architecture, which would hide an x86_64 slice on arm64 runners.
    """
    output = subprocess.run(
        ["nm", "-m", "-arch", "all", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    found: dict[str | None, set[str]] = {}
    arch = None
    for line in output.splitlines():
        header = _ARCH_HEADER.search(line)
        if header:
            arch = header.group(1)
            continue
        match = _DYNAMIC_LOOKUP.search(line) if "(undefined)" in line else None
        if match and match.group(1) in PROVIDER_SYMBOLS:
            found.setdefault(arch, set()).add(match.group(1))
    if None in found:
        found[" ".join(macho_arches(binary))] = found.pop(None)
    return {key: sorted(value) for key, value in found.items()}


def _runtime_archive_arch(name: str) -> str | None:
    if not name.startswith(RUNTIME_ARCHIVE_PREFIX) or not name.endswith(".tar.gz"):
        return None
    return name.removeprefix(RUNTIME_ARCHIVE_PREFIX).split("-", 1)[0]


def _validate_runtime_archive(archive: Path, arch: str) -> list[str]:
    if arch not in MACOS_RUNTIME_ARCHES:
        return [f"{archive.name}: {UNSUPPORTED_MACOS_ARCH_REASON}"]
    errors: list[str] = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            parts = PurePosixPath(member.name).parts
            if len(parts) >= 2 and parts[0] == "macos" and parts[1] != arch:
                errors.append(
                    f"{archive.name}: contains {member.name}; "
                    f"{UNSUPPORTED_MACOS_ARCH_REASON}"
                )
    return errors


def _macos_slice_prefixes(bundle: zipfile.ZipFile, archive: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    prefixes: list[str] = []
    for name in bundle.namelist():
        path = PurePosixPath(name)
        if path.name != "Info.plist" or path.parent.suffix != ".xcframework":
            continue
        framework = path.parent.as_posix()
        libraries = plistlib.loads(bundle.read(name)).get("AvailableLibraries", [])
        for library in libraries:
            if library.get("SupportedPlatform") != "macos":
                continue
            identifier = library.get("LibraryIdentifier")
            arches = library.get("SupportedArchitectures")
            if arches != MACOS_MACHO_ARCHES:
                errors.append(
                    f"{archive.name}: {framework}/{identifier} declares macOS "
                    f"architectures {arches}; {UNSUPPORTED_MACOS_ARCH_REASON}"
                )
            prefixes.append(f"{framework}/{identifier}/")
    return prefixes, errors


def _validate_spm_archive(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as bundle:
        prefixes, errors = _macos_slice_prefixes(bundle, archive)
        if not prefixes:
            return errors
        with tempfile.TemporaryDirectory(prefix="macos-slice-audit-") as temp:
            for index, member in enumerate(bundle.infolist()):
                if member.is_dir() or not any(member.filename.startswith(p) for p in prefixes):
                    continue
                with bundle.open(member) as stream:
                    if stream.read(4) not in MACHO_MAGIC:
                        continue
                binary = Path(temp) / f"binary-{index}"
                binary.write_bytes(bundle.read(member))
                arches = macho_arches(binary)
                if arches != MACOS_MACHO_ARCHES:
                    errors.append(
                        f"{archive.name}: {member.filename} contains {arches}; "
                        f"{UNSUPPORTED_MACOS_ARCH_REASON}"
                    )
                for arch, symbols in unresolved_provider_symbols(binary).items():
                    errors.append(
                        f"{archive.name}: {member.filename} ({arch}) leaves Gemma "
                        "constraint provider symbols to flat-namespace lookup: "
                        + ", ".join(symbols)
                    )
    return errors


def validate_macos_archives(archive_root: Path) -> list[str]:
    """Audit produced macOS runtime tarballs and macOS slices in SwiftPM zips."""
    if not archive_root.exists():
        return []
    candidates = [
        path
        for path in sorted(archive_root.rglob("*"))
        if path.is_file()
        and "official" not in path.relative_to(archive_root).parts
        and "-official-assets-" not in path.name
    ]
    if any(path.suffix == ".zip" for path in candidates):
        missing = [tool for tool in ("xcrun", "nm") if shutil.which(tool) is None]
        if missing:
            raise RuntimeError(
                "macOS archive validation requires " + ", ".join(missing)
                + "; install/select the Xcode command-line tools."
            )
    errors: list[str] = []
    for path in candidates:
        arch = _runtime_archive_arch(path.name)
        if arch is not None:
            errors.extend(_validate_runtime_archive(path, arch))
        elif path.suffix == ".zip":
            errors.extend(_validate_spm_archive(path))
    return errors
