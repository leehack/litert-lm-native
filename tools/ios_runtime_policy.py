"""Provider-free policy for newly source-built iOS v0.17+ artifacts.

Historical official inputs and non-iOS runtimes retain their existing policy.
This does not establish a minimum supported OS; Mach-O metadata remains authoritative.
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

from ios_framework_metadata import binary_minimum_os, validate_framework_metadata, version_tuple
from litert_lm_symbols import is_at_least

FST_DEFINE = "--define=LITERT_LM_FST_CONSTRAINTS_DISABLED=1"
PROVIDER = "GemmaModelConstraintProvider"
CANDIDATE_MAXIMUM_IOS_FLOOR = "16.4"
MACHO_MAGIC = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def contains_provider(value: str) -> bool:
    return "gemmamodelconstraintprovider" in re.sub(r"[^a-z]", "", value.lower())


def provider_free_ios(upstream_tag: str) -> bool:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", upstream_tag):
        raise ValueError("iOS runtime policy requires an explicit stable upstream compatibility tag")
    return is_at_least(upstream_tag, (0, 17, 0))


def verify_upstream_fst_gate(source_root: Path) -> None:
    """Reject a changed source gate rather than trusting an ignored Bazel define."""
    path = source_root / "runtime/conversation/model_data_processor/BUILD"
    text = path.read_text() if path.is_file() else ""
    if not re.search(r'"LITERT_LM_FST_CONSTRAINTS_DISABLED"\s*:\s*"1"', text):
        raise RuntimeError("Selected upstream source lacks the documented iOS FST disable gate")
    for target in ("gemma3_data_processor", "function_gemma_data_processor", "gemma4_data_processor"):
        match = re.search(r'cc_library\(\s*name = "' + target + r'"(.*?)(?=\ncc_library\(|\Z)', text, re.S)
        block = match.group(1) if match else ""
        if (':litert_lm_fst_constraints_disabled": ["LITERT_LM_FST_CONSTRAINTS_DISABLED"]' not in block
                or not re.search(r'\] \+ select\(\{\s*":litert_lm_fst_constraints_disabled": \[\],\s*"//conditions:default": \[\s*"//runtime/components/constrained_decoding:gemma_model_constraint_provider_lib",\s*\],\s*\}\)', block)
                or 'gemma_model_constraint_provider_lib' not in block):
            raise RuntimeError(f"Selected upstream source lacks the documented FST dependency gate for {target}")


def validate_binary(path: Path, supported_platform: str) -> None:
    """Check both direct load commands and every undefined provider symbol."""
    for tool in ("otool", "nm", "xcrun"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"Provider-free iOS qualification requires {tool}")
    loads = subprocess.run(["otool", "-L", str(path)], check=True, capture_output=True, text=True).stdout
    undefined = subprocess.run(["nm", "-u", str(path)], check=True, capture_output=True, text=True).stdout
    if contains_provider(loads) or contains_provider(undefined):
        raise RuntimeError(f"Provider-free iOS runtime still requires {PROVIDER}: {path}")
    actual = binary_minimum_os(path, supported_platform)
    if version_tuple(actual) > version_tuple(CANDIDATE_MAXIMUM_IOS_FLOOR):
        raise RuntimeError(f"iOS candidate requires {actual}, above {CANDIDATE_MAXIMUM_IOS_FLOOR}: {path}")


def validate_ios_directory(directory: Path, *, remove_unused_provider: bool = False) -> None:
    if not directory.exists():
        return
    provider_paths = sorted((p for p in directory.rglob("*") if contains_provider(p.name)), key=lambda p: len(p.parts))
    binaries = set(directory.rglob("*.dylib"))
    binaries.update(p / p.stem for p in directory.rglob("*.framework") if (p / p.stem).is_file())
    for binary in sorted(binaries):
        if not any(contains_provider(part) for part in binary.relative_to(directory).parts):
            platform = "iPhoneSimulator" if any(p.endswith("-sim") for p in binary.parts) else "iPhoneOS"
            validate_binary(binary, platform)
            if binary.parent.suffix == ".framework":
                validate_framework_metadata(binary.parent, platform)
                _validate_declared_floor((binary.parent / "Info.plist").read_bytes(), binary.parent)
    if provider_paths and not remove_unused_provider:
        raise RuntimeError(f"Provider-free iOS inventory contains {provider_paths[0]}")
    # Only discard unused inputs after validating the entire surviving closure.
    for path in provider_paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _validate_declared_floor(data: bytes, path: Path) -> None:
    declared = plistlib.loads(data).get("MinimumOSVersion")
    if version_tuple(declared) > version_tuple(CANDIDATE_MAXIMUM_IOS_FLOOR):
        raise RuntimeError(f"iOS candidate framework declares {declared}, above {CANDIDATE_MAXIMUM_IOS_FLOOR}: {path}")


def _ios_member(name: str, archive: Path) -> bool:
    parts = PurePosixPath(name).parts
    return (any(part == "ios" or part.startswith("ios-") for part in parts)
            or "-runtime-ios-" in archive.name)


def _validate_member(name: str, data: bytes, archive: Path, platform: str, framework_plist: bytes | None = None) -> None:
    if contains_provider(name):
        raise RuntimeError(f"Provider-free iOS archive contains {name}: {archive}")
    path = PurePosixPath(name)
    framework_binary = path.parent.suffix == ".framework" and path.name == path.parent.stem
    if path.name == "Info.plist" and path.parent.suffix == ".framework":
        _validate_declared_floor(data, archive)
    if data[:4] in MACHO_MAGIC or path.suffix == ".dylib" or framework_binary:
        with tempfile.TemporaryDirectory(prefix="ios-runtime-audit-") as tmp:
            if framework_binary:
                framework = Path(tmp) / path.parent.name
                framework.mkdir()
                binary = framework / path.name
            else:
                binary = Path(tmp) / "binary"
            binary.write_bytes(data)
            validate_binary(binary, platform)
            if framework_binary:
                if framework_plist is None:
                    raise RuntimeError(f"iOS archive framework is missing metadata: {name}: {archive}")
                (binary.parent / "Info.plist").write_bytes(framework_plist)
                validate_framework_metadata(binary.parent, platform)
                _validate_declared_floor(framework_plist, archive)



def _validate_archive_platform(data: bytes, platform: str, archive: Path) -> None:
    """Verify actual slice platforms before granting any macOS exemption."""
    with tempfile.TemporaryDirectory(prefix="apple-slice-platform-") as tmp:
        binary = Path(tmp) / "binary"
        binary.write_bytes(data)
        if platform != "MacOSX":
            binary_minimum_os(binary, platform)
            return
        arches = subprocess.run(
            ["xcrun", "lipo", "-archs", str(binary)],
            check=True, capture_output=True, text=True,
        ).stdout.split()
        if not arches or len(arches) != len(set(arches)):
            raise RuntimeError(f"Missing or ambiguous XCFramework Mach-O architectures: {archive}")
        for arch in arches:
            output = subprocess.run(
                ["xcrun", "vtool", "-arch", arch, "-show-build", str(binary)],
                check=True, capture_output=True, text=True,
            ).stdout
            targets = []
            for command in re.split(r"Load command \d+\s*\n", output)[1:]:
                if re.search(r"\bcmd LC_BUILD_VERSION\b", command):
                    actual = re.search(r"^\s*platform (\S+)\s*$", command, re.MULTILINE)
                    minimum = re.search(r"^\s*minos (\S+)\s*$", command, re.MULTILINE)
                    if actual is None or actual.group(1) != "MACOS" or minimum is None:
                        raise RuntimeError(f"XCFramework macos metadata disagrees with actual Mach-O platform: {archive} ({arch})")
                    targets.append(minimum.group(1))
                elif re.search(r"\bcmd LC_VERSION_MIN_MACOSX\b", command):
                    minimum = re.search(r"^\s*version (\S+)\s*$", command, re.MULTILINE)
                    if minimum is None:
                        raise RuntimeError(f"Missing legacy macOS deployment target: {archive} ({arch})")
                    targets.append(minimum.group(1))
                elif re.search(r"\bcmd LC_VERSION_MIN_IPHONEOS\b", command):
                    raise RuntimeError(f"XCFramework macos metadata disagrees with actual Mach-O platform: {archive} ({arch})")
            if len(targets) != 1:
                raise RuntimeError(f"Missing or ambiguous XCFramework macOS deployment target: {archive} ({arch})")
            version_tuple(targets[0])


def validate_ios_archives(dist_dir: Path) -> None:
    """Inspect produced iOS tarballs and iOS slices inside SwiftPM ZIPs."""
    if not dist_dir.exists():
        return
    for archive in sorted(dist_dir.rglob("*")):
        # Preserved official archives are provenance inputs, not candidate runtimes.
        if "official" in archive.relative_to(dist_dir).parts or "-official-assets-" in archive.name:
            continue
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as file:
                slice_prefixes: dict[str, str] = {}
                xcframeworks = {str(PurePosixPath(name).parents[index])
                               for name in file.namelist()
                               for index in range(len(PurePosixPath(name).parents))
                               if PurePosixPath(name).parents[index].suffix == ".xcframework"}
                for framework in sorted(xcframeworks):
                    metadata = framework + "/Info.plist"
                    if metadata not in file.namelist():
                        raise RuntimeError(f"XCFramework archive is missing platform metadata: {archive}")
                    info = plistlib.loads(file.read(metadata))
                    libraries = info.get("AvailableLibraries")
                    if not isinstance(libraries, list) or not libraries:
                        raise RuntimeError(f"XCFramework archive is missing slice metadata: {archive}")
                    for library in libraries:
                        platform = library.get("SupportedPlatform")
                        variant = library.get("SupportedPlatformVariant")
                        identifier = library.get("LibraryIdentifier")
                        if (platform not in {"ios", "macos"}
                                or variant not in ({None, "simulator"} if platform == "ios" else {None})
                                or not isinstance(identifier, str) or not identifier):
                            raise RuntimeError(f"Unsupported XCFramework platform/variant metadata: {archive}")
                        prefix = framework + "/" + identifier + "/"
                        if prefix in slice_prefixes:
                            raise RuntimeError(f"Ambiguous XCFramework slice metadata: {archive}")
                        slice_prefixes[prefix] = ("MacOSX" if platform == "macos" else "iPhoneSimulator" if variant == "simulator" else "iPhoneOS")
                checked_slices = dict.fromkeys(slice_prefixes, 0)
                for member in file.infolist():
                    if member.is_dir():
                        continue
                    with file.open(member) as stream:
                        magic = stream.read(4)
                    if magic not in MACHO_MAGIC:
                        continue
                    matches = [prefix for prefix in slice_prefixes if member.filename.startswith(prefix)]
                    if any(member.filename.startswith(framework + "/") for framework in xcframeworks):
                        if len(matches) != 1:
                            raise RuntimeError(f"Missing or ambiguous XCFramework slice metadata for Mach-O binary: {archive} ({member.filename})")
                        prefix = matches[0]
                        _validate_archive_platform(file.read(member), slice_prefixes[prefix], archive)
                        checked_slices[prefix] += 1
                for prefix, checked in checked_slices.items():
                    if not checked:
                        raise RuntimeError(f"XCFramework slice has no inspectable Mach-O binary: {archive} ({prefix})")
                for member in file.infolist():
                    declared_platform = next((platform for prefix, platform in slice_prefixes.items() if member.filename.startswith(prefix)), None)
                    is_ios = declared_platform != "MacOSX" if declared_platform is not None else _ios_member(member.filename, archive)
                    if is_ios and contains_provider(member.filename):
                        raise RuntimeError(f"Provider-free iOS archive contains {member.filename}: {archive}")
                    if not member.is_dir() and is_ios:
                        platform = declared_platform or ("iPhoneSimulator" if "simulator" in member.filename else "iPhoneOS")
                        metadata = str(PurePosixPath(member.filename).parent / "Info.plist")
                        plist = file.read(metadata) if metadata in file.namelist() else None
                        _validate_member(member.filename, file.read(member), archive, platform, plist)
        elif archive.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive) as file:
                for member in file:
                    if _ios_member(member.name, archive) and contains_provider(member.name):
                        raise RuntimeError(f"Provider-free iOS archive contains {member.name}: {archive}")
                    if member.isfile() and _ios_member(member.name, archive):
                        stream = file.extractfile(member)
                        if stream is not None:
                            simulator = any(part.endswith("-sim") or "simulator" in part for part in PurePosixPath(member.name).parts) or "-sim-" in archive.name
                            metadata = str(PurePosixPath(member.name).parent / "Info.plist")
                            plist_stream = file.extractfile(metadata) if metadata in file.getnames() else None
                            plist = plist_stream.read() if plist_stream is not None else None
                            _validate_member(member.name, stream.read(), archive, "iPhoneSimulator" if simulator else "iPhoneOS", plist)
