#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from runtime_dependency_utils import elf_needed_libraries, is_elf, is_system_needed

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
BRIDGE_PACKAGE_ROOT = REPO_ROOT / "native"
UPSTREAM_REPO = "google-ai-edge/LiteRT-LM"
MACOS_MINIMUM_OS = "14.0"
UPSTREAM_ARCHIVE_URL = (
    "https://github.com/google-ai-edge/LiteRT-LM/archive/refs/tags/{tag}.tar.gz"
)
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
        ],
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
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

REQUIRED_C_API_SYMBOLS = [
    b"litert_lm_engine_settings_create",
    b"litert_lm_engine_create",
    b"litert_lm_conversation_create",
    b"litert_lm_conversation_send_message_stream",
]

REQUIRED_BRIDGE_SYMBOLS = [
    b"stream_proxy_load_global",
    b"stream_proxy_create",
    b"stream_proxy_delete",
    b"stream_proxy_free_string",
]


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    if os.name == "nt":
        subprocess.run(printable, cwd=cwd, env=env, check=True, shell=True)
    else:
        subprocess.run(command, cwd=cwd, env=env, check=True)


def download_upstream(tag: str, work_dir: Path) -> Path:
    archive_path = work_dir / f"LiteRT-LM-{tag}.tar.gz"
    url = UPSTREAM_ARCHIVE_URL.format(tag=tag)
    print(f"Downloading {url}", flush=True)
    urllib.request.urlretrieve(url, archive_path)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(work_dir, filter="data")
    candidates = [path for path in work_dir.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one extracted source directory, got {candidates}")
    source_root = candidates[0]
    patch_upstream_workspace(source_root)
    return source_root


def patch_upstream_workspace(source_root: Path) -> None:
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
        if ZLIB_GITHUB_MIRROR_URL in text:
            return
        raise RuntimeError(f"Expected zlib URL not found in {workspace}")
    workspace.write_text(text.replace(needle, replacement), encoding="utf-8")
    print(
        "Patched upstream WORKSPACE minizip archive URLs with GitHub zlib mirror",
        flush=True,
    )


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


def build_runtime(source_root: Path, platform: str, arch: str, jobs: str | None) -> Path:
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
    if platform == "macos":
        command.append(f"--macos_minimum_os={MACOS_MINIMUM_OS}")
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
    if platform == "macos":
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


def validate_exported_symbols(output: Path) -> None:
    data = output.read_bytes()
    required_symbols = REQUIRED_C_API_SYMBOLS + REQUIRED_BRIDGE_SYMBOLS
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Build the upstream {UPSTREAM_REPO} C runtime library."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--jobs")
    args = parser.parse_args()

    key = (args.platform, args.arch)
    if key not in RUNTIME_TARGETS:
        supported = ", ".join(f"{p}/{a}" for p, a in sorted(RUNTIME_TARGETS))
        raise SystemExit(f"Unsupported target {args.platform}/{args.arch}; supported: {supported}")

    if args.source_root:
        source_root = args.source_root.resolve()
        output = build_runtime(source_root, args.platform, args.arch, args.jobs)
        validate_exported_symbols(output)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
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
        source_root = download_upstream(args.upstream_tag, Path(tmp))
        output = build_runtime(source_root, args.platform, args.arch, args.jobs)
        validate_exported_symbols(output)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
