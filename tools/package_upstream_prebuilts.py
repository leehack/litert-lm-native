#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"

UPSTREAM_SOURCE_URL = (
    "https://github.com/google-ai-edge/LiteRT-LM/archive/refs/tags/{tag}.tar.gz"
)

PREBUILT_TARGETS = {
    "android_arm64": ("android", "arm64"),
    "android_x86_64": ("android", "x64"),
    "ios_arm64": ("ios", "arm64"),
    "ios_sim_arm64": ("ios", "arm64-sim"),
    "linux_arm64": ("linux", "arm64"),
    "linux_x86_64": ("linux", "x64"),
    "macos_arm64": ("macos", "arm64"),
    "windows_x86_64": ("windows", "x64"),
}

LIB_SUFFIXES = (".so", ".dylib", ".dll", ".lib", ".a")


def download_source(tag: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading upstream source archive for {tag}", flush=True)
    request = urllib.request.Request(
        UPSTREAM_SOURCE_URL.format(tag=tag),
        headers={"User-Agent": "litert-lm-native-prebuilt-packager"},
    )
    with urllib.request.urlopen(request) as response, output.open("wb") as file:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file.write(chunk)


def extract_source(archive: Path, output_dir: Path) -> Path:
    print(f"Extracting {archive}", flush=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(output_dir, filter="data")
    roots = [path for path in output_dir.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise SystemExit(f"Expected one source root in {output_dir}, got {roots}")
    return roots[0]


def copy_prebuilts(source_root: Path, clean: bool) -> int:
    copied = 0
    for upstream_name, (platform, arch) in PREBUILT_TARGETS.items():
        source_dir = source_root / "prebuilt" / upstream_name
        if not source_dir.is_dir():
            print(f"missing upstream prebuilt dir: {source_dir}", flush=True)
            continue
        target_dir = BIN_DIR / platform / arch
        if clean and target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        for file in sorted(source_dir.iterdir()):
            if not file.is_file() or not file.name.endswith(LIB_SUFFIXES):
                continue
            shutil.copy2(file, target_dir / file.name)
            copied += 1
        print(f"Packaged {upstream_name} -> {target_dir}", flush=True)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy upstream LiteRT-LM prebuilt runtime libs into bin/."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    if args.source_root is not None:
        source_root = args.source_root
        if not source_root.is_dir():
            raise SystemExit(f"source root does not exist: {source_root}")
        copied = copy_prebuilts(source_root, clean=args.clean)
    else:
        with tempfile.TemporaryDirectory(prefix="litert-lm-native-") as temp:
            temp_dir = Path(temp)
            archive = temp_dir / f"LiteRT-LM-{args.upstream_tag}.tar.gz"
            download_source(args.upstream_tag, archive)
            source_root = extract_source(archive, temp_dir / "src")
            copied = copy_prebuilts(source_root, clean=args.clean)

    print(f"Copied {copied} upstream prebuilt libraries", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
