#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import quote

from download_utils import download_to_path
from git_lfs_utils import materialize_git_lfs_libraries
from litert_lm_symbols import (
    has_asr_bridge,
    required_bridge_symbols,
    required_c_api_symbols,
    uses_stream_chunk_api,
)
from package_upstream_prebuilts import apply_prebuilt_overrides
from runtime_dependency_utils import (
    elf_has_global_flag,
    elf_needed_libraries,
    is_elf,
    is_system_needed,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
BRIDGE_PACKAGE_ROOT = REPO_ROOT / "native"
UPSTREAM_REPO = "google-ai-edge/LiteRT-LM"
MACOS_MINIMUM_OS = "14.0"
UPSTREAM_ARCHIVE_URL = (
    "https://github.com/google-ai-edge/LiteRT-LM/archive/{ref}.tar.gz"
)
USER_AGENT = "litert-lm-native-build"
ZLIB_URL = "https://zlib.net/fossils/zlib-1.3.1.tar.gz"
ZLIB_GITHUB_MIRROR_URL = (
    "https://github.com/madler/zlib/releases/download/v1.3.1/"
    "zlib-1.3.1.tar.gz"
)

RUNTIME_TARGETS = {
    ("android", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_config": "android_arm64",
        "bazel_options": [
            "--linkopt=-Wl,-z,max-page-size=16384",
            "--linkopt=-Wl,-z,common-page-size=16384",
            "--linkopt=-Wl,-z,global",
        ],
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("android", "x64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_config": "android_x86_64",
        "bazel_options": [
            "--linkopt=-Wl,-z,max-page-size=16384",
            "--linkopt=-Wl,-z,common-page-size=16384",
            "--linkopt=-Wl,-z,global",
        ],
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("ios", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.dylib",
        "bazel_config": "ios_arm64",
        "output": "bazel-bin/bridge/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("ios", "arm64-sim"): {
        "bazel_target": "//bridge:libLiteRtLm.dylib",
        "bazel_config": "ios_sim_arm64",
        "output": "bazel-bin/bridge/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("linux", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_configs": ["linux", "linux_arm64"],
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("linux", "x64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_config": "linux",
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("macos", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.dylib",
        "bazel_configs": ["macos", "macos_arm64"],
        "output": "bazel-bin/bridge/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("macos", "x64"): {
        "bazel_target": "//bridge:libLiteRtLm.dylib",
        "bazel_config": "macos",
        "bazel_options": [
            "--cpu=darwin_x86_64",
            "--platforms=@build_bazel_apple_support//platforms:darwin_x86_64",
        ],
        "output": "bazel-bin/bridge/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("windows", "x64"): {
        "bazel_target": "//bridge:LiteRtLm.dll",
        "bazel_config": "windows",
        "output": "bazel-bin/bridge/LiteRtLm.dll",
        "library": "LiteRtLm.dll",
    },
}

PREBUILT_TARGETS = {
    ("android", "arm64"): "android_arm64",
    ("android", "x64"): "android_x86_64",
    ("ios", "arm64"): "ios_arm64",
    ("ios", "arm64-sim"): "ios_sim_arm64",
    ("linux", "arm64"): "linux_arm64",
    ("linux", "x64"): "linux_x86_64",
    ("macos", "arm64"): "macos_arm64",
    ("windows", "x64"): "windows_x86_64",
}
LIB_SUFFIXES = (".so", ".dylib", ".dll", ".lib", ".a")


def source_archive_path(work_dir: Path, upstream_ref: str) -> Path:
    ref_digest = hashlib.sha256(upstream_ref.encode("utf-8")).hexdigest()
    return work_dir / f"LiteRT-LM-{ref_digest}.tar.gz"


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    if os.name == "nt":
        subprocess.run(printable, cwd=cwd, env=env, check=True, shell=True)
    else:
        subprocess.run(command, cwd=cwd, env=env, check=True)


def download_upstream(
    upstream_ref: str, compatibility_tag: str, work_dir: Path
) -> Path:
    archive_path = source_archive_path(work_dir, upstream_ref)
    url = UPSTREAM_ARCHIVE_URL.format(ref=quote(upstream_ref, safe=""))
    print(f"Downloading {url}", flush=True)
    download_to_path(
        url,
        archive_path,
        headers={"User-Agent": USER_AGENT},
        label=f"LiteRT-LM {upstream_ref} source archive",
    )
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(work_dir, filter="data")
    candidates = [path for path in work_dir.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one extracted source directory, got {candidates}")
    source_root = candidates[0]
    patch_upstream_workspace(
        source_root,
        patch_ios_framework_paths=has_asr_bridge(compatibility_tag),
    )
    return source_root


def patch_upstream_workspace(
    source_root: Path,
    *,
    patch_ios_framework_paths: bool = True,
) -> None:
    workspace = source_root / "WORKSPACE"
    text = workspace.read_text(encoding="utf-8")
    needle = f'    url = "{ZLIB_URL}",'
    replacement = (
        "    urls = [\n"
        f'        "{ZLIB_GITHUB_MIRROR_URL}",\n'
        f'        "{ZLIB_URL}",\n'
        "    ],"
    )
    if needle not in text:
        if ZLIB_GITHUB_MIRROR_URL not in text:
            raise RuntimeError(f"Expected zlib URL not found in {workspace}")
    else:
        text = text.replace(needle, replacement)
    litert_archive = 'http_archive(\n    name = "litert",\n'
    litert_archive_with_patch = (
        'http_archive(\n'
        '    name = "litert",\n'
        '    patch_args = ["-p1"],\n'
        '    patches = ["@//bridge:litert_ios_framework_paths.patch"],\n'
    )
    if patch_ios_framework_paths and litert_archive_with_patch not in text:
        if litert_archive not in text:
            raise RuntimeError(f"Expected LiteRT archive not found in {workspace}")
        text = text.replace(litert_archive, litert_archive_with_patch, 1)
    workspace.write_text(text, encoding="utf-8")
    print(
        "Patched upstream WORKSPACE dependency URLs and iOS framework paths",
        flush=True,
    )


def patch_upstream_ios_sampler_path(source_root: Path) -> None:
    sampler = source_root / "runtime" / "components" / "sampler_factory.cc"
    text = sampler.read_text(encoding="utf-8")
    original = '"libLiteRtTopKMetalSampler.dylib"'
    replacement = (
        '"@executable_path/Frameworks/LiteRtTopKMetalSampler.framework/'
        'LiteRtTopKMetalSampler"'
    )
    if replacement in text:
        return
    if text.count(original) != 1:
        raise RuntimeError(
            f"Expected one Metal sampler library path in {sampler}"
        )
    sampler.write_text(text.replace(original, replacement), encoding="utf-8")
    print("Patched upstream iOS Metal sampler framework path", flush=True)


def bazel_command() -> list[str]:
    if shutil.which("bazelisk"):
        return ["bazelisk"]
    if shutil.which("npx"):
        return ["npx", "--yes", "@bazel/bazelisk@latest"]
    if shutil.which("bazel"):
        return ["bazel"]
    raise RuntimeError("Could not find bazelisk, bazel, or npx")


def bazel_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt":
        return resolved.as_posix()
    return str(resolved)


def prepare_bridge_package(source_root: Path) -> list[str]:
    if os.name != "nt":
        package_path = os.pathsep.join(
            [bazel_path(BRIDGE_PACKAGE_ROOT), bazel_path(source_root)]
        )
        return [f"--package_path={package_path}"]

    # Bazel 7.6.1 on the Windows 2025 hosted image rewrites absolute
    # --package_path entries like D:/a/... into /a/... during package loading.
    # Copying the small downstream bridge package into the extracted upstream
    # tree avoids that parser path while keeping the upstream archive untouched.
    bridge_source = BRIDGE_PACKAGE_ROOT / "bridge"
    bridge_destination = source_root / "bridge"
    if bridge_destination.exists():
        shutil.rmtree(bridge_destination)
    shutil.copytree(bridge_source, bridge_destination)
    print(f"Staged bridge package at {bridge_destination}", flush=True)
    return []


def build_runtime(
    source_root: Path,
    platform: str,
    arch: str,
    upstream_tag: str,
    jobs: str | None,
    upstream_ref: str | None = None,
) -> Path:
    if platform == "ios" and has_asr_bridge(upstream_tag):
        patch_upstream_ios_sampler_path(source_root)
    prebuilt_target = PREBUILT_TARGETS.get((platform, arch))
    if prebuilt_target is not None:
        source_dir = source_root / "prebuilt" / prebuilt_target
        materialized = materialize_git_lfs_libraries(
            source_dir,
            upstream_tag=upstream_ref or upstream_tag,
            source_root=source_root,
            suffixes=LIB_SUFFIXES,
        )
        if materialized:
            print(
                f"Materialized {materialized} pointer-backed libraries for "
                f"{platform}/{arch}",
                flush=True,
            )
    target = RUNTIME_TARGETS[(platform, arch)]
    configs = [
        f"--config={config}"
        for config in target.get("bazel_configs", [target.get("bazel_config")])
        if config
    ]
    command = bazel_command()
    output_user_root = os.environ.get("BAZEL_OUTPUT_USER_ROOT")
    if output_user_root:
        if not os.path.isabs(output_user_root):
            output_user_root = bazel_path(REPO_ROOT / output_user_root)
        elif os.name == "nt":
            output_user_root = Path(output_user_root).resolve().as_posix()
        command.append(f"--output_user_root={output_user_root}")
    bridge_options = prepare_bridge_package(source_root)
    command += [
        "build",
        *bridge_options,
        *configs,
        *target.get("bazel_options", []),
        target["bazel_target"],
        "--define=litert_link_capi_so=true",
        "--define=resolve_symbols_in_exec=false",
    ]
    if uses_stream_chunk_api(upstream_tag):
        command.append("--define=litert_lm_stream_chunk_api=true")
    if has_asr_bridge(upstream_tag):
        command.append("--define=litert_lm_asr_api=true")
    if platform == "macos":
        command.append(f"--macos_minimum_os={MACOS_MINIMUM_OS}")
    if platform == "ios":
        command.append("--ios_minimum_os=13.0")
    if jobs:
        command.append(f"--jobs={jobs}")
    run(command, source_root)

    if "output" in target:
        output = source_root / target["output"]
        if not output.is_file():
            raise RuntimeError(f"Expected build output missing: {output}")
        return output

    matches = sorted(source_root.glob(target["output_glob"]))
    if not matches:
        raise RuntimeError(f"Expected build output missing: {target['output_glob']}")
    return matches[0]


def stage_runtime(output: Path, platform: str, arch: str) -> Path:
    target = RUNTIME_TARGETS[(platform, arch)]
    stage_dir = BIN_DIR / platform / arch
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged = stage_dir / target["library"]
    copy_artifact(output, staged)
    print(f"Staged {staged}", flush=True)
    return staged


def copy_artifact(source: Path, destination: Path) -> None:
    destination.unlink(missing_ok=True)
    shutil.copy2(source, destination)


def stage_runtime_dependencies(
    output: Path,
    source_root: Path,
    platform: str,
    arch: str,
) -> None:
    if platform == "windows":
        stage_windows_runtime_dependencies(source_root, arch)
        return
    if platform in {"ios", "macos"}:
        stage_macho_runtime_dependencies(output, source_root, platform, arch)
        return

    stage_dir = BIN_DIR / platform / arch
    staged = stage_dir / RUNTIME_TARGETS[(platform, arch)]["library"]
    queued = [staged]
    seen = set()
    dependency_cache: dict[str, Path | None] = {}

    while queued:
        current = queued.pop()
        if current in seen:
            continue
        seen.add(current)
        if not is_elf(current):
            continue
        for library_name in elf_needed_libraries(current):
            if is_system_needed(platform, library_name):
                continue
            destination = stage_dir / library_name
            if not destination.exists():
                dependency = find_runtime_dependency(
                    source_root,
                    output,
                    library_name,
                    dependency_cache,
                )
                if dependency is None:
                    raise RuntimeError(
                        f"{current} depends on {library_name}, but that library "
                        "was not found in the Bazel output tree."
                    )
                copy_artifact(dependency, destination)
                print(f"Staged runtime dependency {destination}", flush=True)
            queued.append(destination)


def stage_runtime_overrides(upstream_tag: str, platform: str, arch: str) -> None:
    overridden = apply_prebuilt_overrides(
        upstream_tag,
        platform=platform,
        arch=arch,
    )
    if overridden:
        print(
            f"Applied {overridden} pinned runtime overrides for "
            f"{platform}/{arch}",
            flush=True,
        )


def stage_windows_runtime_dependencies(source_root: Path, arch: str) -> None:
    prebuilt_target = PREBUILT_TARGETS.get(("windows", arch))
    if prebuilt_target is None:
        return
    source_dir = source_root / "prebuilt" / prebuilt_target
    stage_dir = BIN_DIR / "windows" / arch
    stage_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_dir.glob("*.dll")):
        destination = stage_dir / source.name
        copy_artifact(source, destination)
        print(f"Staged runtime dependency {destination}", flush=True)


def stage_macho_runtime_dependencies(
    output: Path,
    source_root: Path,
    platform: str,
    arch: str,
) -> None:
    stage_dir = BIN_DIR / platform / arch
    staged = stage_dir / RUNTIME_TARGETS[(platform, arch)]["library"]
    queued = [staged]
    seen = set()
    dependency_cache: dict[str, Path | None] = {}

    while queued:
        current = queued.pop()
        if current in seen:
            continue
        seen.add(current)
        for install_name in macho_needed_libraries(current):
            if is_system_macho_needed(install_name):
                continue
            library_name = Path(install_name).name
            if library_name == current.name:
                continue
            destination = stage_dir / library_name
            if not destination.exists():
                dependency = find_runtime_dependency(
                    source_root,
                    output,
                    library_name,
                    dependency_cache,
                )
                if dependency is None:
                    raise RuntimeError(
                        f"{current} depends on {install_name}, but {library_name} "
                        "was not found in the Bazel output tree."
                    )
                copy_artifact(dependency, destination)
                print(f"Staged runtime dependency {destination}", flush=True)
            queued.append(destination)


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


def find_runtime_dependency(
    source_root: Path,
    output: Path,
    library_name: str,
    cache: dict[str, Path | None],
) -> Path | None:
    if library_name in cache:
        return cache[library_name]

    roots = [
        output.parent,
        output.parent / f"{output.name}.runfiles",
        source_root / "bazel-bin",
        source_root / "bazel-out",
    ]
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob(library_name):
            if candidate.is_file():
                cache[library_name] = candidate
                return candidate
    cache[library_name] = None
    return None


def validate_exported_symbols(output: Path, upstream_tag: str) -> None:
    data = output.read_bytes()
    required_symbols = (
        required_c_api_symbols(upstream_tag)
        + required_bridge_symbols(upstream_tag)
    )
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
    print(f"Validated LiteRT-LM and bridge symbols in {output}", flush=True)


def validate_android_global_visibility(output: Path, platform: str) -> None:
    if platform != "android":
        return
    if not elf_has_global_flag(output):
        raise RuntimeError(
            f"{output} is missing the ELF DF_1_GLOBAL flag required for "
            "dlopened LiteRT GPU sampler plugins to resolve runtime symbols."
        )
    print(f"Validated Android global symbol visibility in {output}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Build the upstream {UPSTREAM_REPO} C runtime library."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument(
        "--upstream-ref",
        help=(
            "Exact source tag or commit. Defaults to --upstream-tag; development "
            "builds pass a full commit while --upstream-tag remains the stable "
            "compatibility baseline."
        ),
    )
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--jobs")
    args = parser.parse_args()
    upstream_ref = args.upstream_ref or args.upstream_tag

    key = (args.platform, args.arch)
    if key not in RUNTIME_TARGETS:
        supported = ", ".join(f"{p}/{a}" for p, a in sorted(RUNTIME_TARGETS))
        raise SystemExit(f"Unsupported target {args.platform}/{args.arch}; supported: {supported}")

    if args.source_root:
        source_root = args.source_root.resolve()
        output = build_runtime(
            source_root,
            args.platform,
            args.arch,
            args.upstream_tag,
            args.jobs,
            upstream_ref,
        )
        validate_exported_symbols(output, args.upstream_tag)
        validate_android_global_visibility(output, args.platform)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
        stage_runtime_overrides(args.upstream_tag, args.platform, args.arch)
        return 0

    tmp_parent = None
    if os.name == "nt":
        tmp_parent = REPO_ROOT / ".tmp"
        tmp_parent.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="litert-lm-native-build-",
        dir=tmp_parent,
        ignore_cleanup_errors=os.name == "nt",
    ) as tmp:
        source_root = download_upstream(
            upstream_ref, args.upstream_tag, Path(tmp)
        )
        output = build_runtime(
            source_root,
            args.platform,
            args.arch,
            args.upstream_tag,
            args.jobs,
            upstream_ref,
        )
        validate_exported_symbols(output, args.upstream_tag)
        validate_android_global_visibility(output, args.platform)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
        stage_runtime_overrides(args.upstream_tag, args.platform, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
