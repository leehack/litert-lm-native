#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
STREAM_PROXY_SOURCE = REPO_ROOT / "native" / "stream_proxy" / "stream_proxy.c"

STREAM_PROXY_LIBRARIES = {
    ("android", "arm64"): "libStreamProxy.so",
    ("android", "x64"): "libStreamProxy.so",
    ("linux", "arm64"): "libStreamProxy.so",
    ("linux", "x64"): "libStreamProxy.so",
    ("macos", "arm64"): "libStreamProxy.dylib",
    ("macos", "x64"): "libStreamProxy.dylib",
    ("windows", "x64"): "StreamProxy.dll",
}

REQUIRED_STREAM_PROXY_SYMBOLS = [
    b"stream_proxy_load_global",
    b"stream_proxy_create",
    b"stream_proxy_delete",
    b"stream_proxy_free_string",
]


def run(command: list[str], cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def android_clang(arch: str) -> Path:
    ndk_home = os.environ.get("ANDROID_NDK_HOME")
    if not ndk_home:
        raise RuntimeError("ANDROID_NDK_HOME is required to build Android StreamProxy")

    host_tag = {
        "darwin": "darwin-x86_64",
        "linux": "linux-x86_64",
        "win32": "windows-x86_64",
    }.get(sys.platform)
    if host_tag is None:
        raise RuntimeError(f"Unsupported Android build host: {sys.platform}")

    target = {
        "arm64": "aarch64-linux-android",
        "x64": "x86_64-linux-android",
    }[arch]
    api_level = os.environ.get("ANDROID_API_LEVEL", "23")
    suffix = ".cmd" if sys.platform == "win32" else ""
    compiler = (
        Path(ndk_home)
        / "toolchains"
        / "llvm"
        / "prebuilt"
        / host_tag
        / "bin"
        / f"{target}{api_level}-clang{suffix}"
    )
    if not compiler.is_file():
        raise RuntimeError(f"Android clang not found: {compiler}")
    return compiler


def compiler_command(platform_name: str, arch: str, output: Path) -> list[str]:
    source = str(STREAM_PROXY_SOURCE)
    if platform_name == "android":
        return [
            str(android_clang(arch)),
            "-shared",
            "-fPIC",
            "-O2",
            "-std=c11",
            "-fvisibility=hidden",
            "-Wl,-z,max-page-size=16384",
            "-Wl,-z,common-page-size=16384",
            "-o",
            str(output),
            source,
            "-ldl",
        ]

    if platform_name == "linux":
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if cc is None:
            raise RuntimeError("Could not find a C compiler for Linux StreamProxy")
        return [
            cc,
            "-shared",
            "-fPIC",
            "-O2",
            "-std=c11",
            "-fvisibility=hidden",
            "-o",
            str(output),
            source,
            "-ldl",
        ]

    if platform_name == "macos":
        cc = shutil.which("cc") or shutil.which("clang")
        if cc is None:
            raise RuntimeError("Could not find a C compiler for macOS StreamProxy")
        mac_arch = "arm64" if arch == "arm64" else "x86_64"
        return [
            cc,
            "-dynamiclib",
            "-O2",
            "-std=c11",
            "-fvisibility=hidden",
            "-arch",
            mac_arch,
            "-o",
            str(output),
            source,
        ]

    if platform_name == "windows":
        clang_cl = shutil.which("clang-cl")
        if clang_cl is not None:
            return [
                clang_cl,
                "/LD",
                "/O2",
                "/TC",
                f"/Fe:{output}",
                source,
            ]

        cl = shutil.which("cl")
        if cl is not None:
            return [
                cl,
                "/LD",
                "/O2",
                "/TC",
                f"/Fe:{output}",
                source,
            ]

        clang = shutil.which("clang")
        if clang is not None:
            return [
                clang,
                "-shared",
                "-O2",
                "-std=c11",
                "-o",
                str(output),
                source,
            ]

        raise RuntimeError("Could not find clang-cl, cl, or clang for Windows StreamProxy")

    raise RuntimeError(f"Unsupported StreamProxy target: {platform_name}/{arch}")


def validate_stream_proxy_symbols(output: Path) -> None:
    data = output.read_bytes()
    missing = [
        symbol.decode("ascii")
        for symbol in REQUIRED_STREAM_PROXY_SYMBOLS
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required StreamProxy symbols: "
            + ", ".join(missing)
        )
    print(f"Validated StreamProxy symbols in {output}", flush=True)


def cleanup_windows_import_outputs(output: Path) -> None:
    for suffix in (".exp", ".lib", ".obj"):
        candidate = output.with_suffix(suffix)
        if candidate.exists():
            candidate.unlink()


def build_stream_proxy(platform_name: str, arch: str, output_dir: Path = BIN_DIR) -> Path:
    key = (platform_name, arch)
    if key not in STREAM_PROXY_LIBRARIES:
        supported = ", ".join(f"{p}/{a}" for p, a in sorted(STREAM_PROXY_LIBRARIES))
        raise RuntimeError(
            f"Unsupported StreamProxy target {platform_name}/{arch}; "
            f"supported: {supported}"
        )
    if not STREAM_PROXY_SOURCE.is_file():
        raise RuntimeError(f"Missing StreamProxy source: {STREAM_PROXY_SOURCE}")

    stage_dir = output_dir / platform_name / arch
    stage_dir.mkdir(parents=True, exist_ok=True)
    output = stage_dir / STREAM_PROXY_LIBRARIES[key]
    if output.exists():
        output.unlink()

    run(compiler_command(platform_name, arch, output), REPO_ROOT)
    if platform.system() == "Windows":
        cleanup_windows_import_outputs(output)
    if not output.is_file():
        raise RuntimeError(f"Expected StreamProxy output missing: {output}")
    validate_stream_proxy_symbols(output)
    print(f"Staged {output}", flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the StreamProxy helper library.")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--output-dir", type=Path, default=BIN_DIR)
    args = parser.parse_args()

    build_stream_proxy(args.platform, args.arch, args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
