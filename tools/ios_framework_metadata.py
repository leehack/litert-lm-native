"""Derive iOS framework metadata from the packaged Mach-O deployment targets."""
from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", value) is None:
        raise RuntimeError(f"Invalid iOS minimum version: {value!r}")
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (3 - len(parts))


def binary_minimum_os(binary: Path, supported_platform: str) -> str:
    expected = {"iPhoneOS": "IOS", "iPhoneSimulator": "IOSSIMULATOR"}.get(supported_platform)
    if expected is None:
        raise RuntimeError(f"Unsupported iOS framework platform: {supported_platform}")
    arches = subprocess.run(
        ["xcrun", "lipo", "-archs", str(binary)],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    if not arches or len(arches) != len(set(arches)):
        raise RuntimeError(f"Missing or ambiguous Mach-O architectures: {binary}")
    versions: list[str] = []
    for arch in arches:
        output = subprocess.run(
            ["xcrun", "vtool", "-arch", arch, "-show-build", str(binary)],
            check=True, capture_output=True, text=True,
        ).stdout
        commands = re.split(r"Load command \d+\s*\n", output)[1:]
        targets: list[str] = []
        for command in commands:
            if re.search(r"\bcmd LC_BUILD_VERSION\b", command):
                platform = re.search(r"^\s*platform (\S+)\s*$", command, re.MULTILINE)
                minimum = re.search(r"^\s*minos (\S+)\s*$", command, re.MULTILINE)
                if platform is None or platform.group(1) != expected or minimum is None:
                    raise RuntimeError(f"Invalid {supported_platform} build target in {binary} ({arch})")
                targets.append(minimum.group(1))
            elif re.search(r"\bcmd LC_VERSION_MIN_IPHONEOS\b", command):
                # Older simulator binaries identify their platform by architecture.
                if (arch in {"i386", "x86_64"}) != (expected == "IOSSIMULATOR"):
                    raise RuntimeError(f"Wrong legacy iOS platform in {binary} ({arch})")
                minimum = re.search(r"^\s*version (\S+)\s*$", command, re.MULTILINE)
                if minimum is None:
                    raise RuntimeError(f"Missing legacy iOS version in {binary} ({arch})")
                targets.append(minimum.group(1))
        if len(targets) != 1:
            raise RuntimeError(f"Expected one iOS deployment target in {binary} ({arch})")
        version_tuple(targets[0])
        versions.extend(targets)
    return max(versions, key=version_tuple)


def framework_minimum_os(binary: Path, supported_platform: str, minimum: str) -> str:
    return max((minimum, binary_minimum_os(binary, supported_platform)), key=version_tuple)


def validate_framework_metadata(framework: Path, supported_platform: str) -> None:
    plist = plistlib.loads((framework / "Info.plist").read_bytes())
    if plist.get("CFBundleExecutable") != framework.stem:
        raise RuntimeError(f"Incorrect iOS framework executable: {framework}")
    if plist.get("CFBundleSupportedPlatforms") != [supported_platform]:
        raise RuntimeError(f"Incorrect iOS framework platform: {framework}")
    declared = plist.get("MinimumOSVersion")
    actual = binary_minimum_os(framework / framework.stem, supported_platform)
    if version_tuple(declared) < version_tuple(actual):
        raise RuntimeError(
            f"{framework} declares MinimumOSVersion {declared}, "
            f"but its binary requires {actual}"
        )


def update_framework_minimum_os(
    framework: Path, supported_platform: str, minimum: str | None = None
) -> None:
    """Update a staging copy after merging slices; never lower its existing floor."""
    path = framework / "Info.plist"
    plist = plistlib.loads(path.read_bytes())
    existing = plist.get("MinimumOSVersion")
    if minimum is not None:
        existing = max((existing, minimum), key=version_tuple)
    plist["MinimumOSVersion"] = framework_minimum_os(
        framework / framework.stem, supported_platform, existing
    )
    path.write_bytes(plistlib.dumps(plist))
    validate_framework_metadata(framework, supported_platform)
