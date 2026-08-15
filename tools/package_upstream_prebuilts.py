#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
import tempfile
from pathlib import Path

from download_utils import download_to_path
from git_lfs_utils import materialize_git_lfs_libraries
from prebuilt_overrides import (
    UPSTREAM_MEDIA_BASE_URL,
    PrebuiltOverride,
    prebuilt_overrides,
)

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
    print(f"Downloading upstream source archive for {tag}", flush=True)
    download_to_path(
        UPSTREAM_SOURCE_URL.format(tag=tag),
        output,
        headers={"User-Agent": "litert-lm-native-prebuilt-packager"},
        label=f"LiteRT-LM {tag} source archive",
    )


def extract_source(archive: Path, output_dir: Path) -> Path:
    print(f"Extracting {archive}", flush=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(output_dir, filter="data")
    roots = [path for path in output_dir.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise SystemExit(f"Expected one source root in {output_dir}, got {roots}")
    return roots[0]


def copy_prebuilts(source_root: Path, upstream_tag: str, clean: bool) -> int:
    copied = 0
    for upstream_name, (platform, arch) in PREBUILT_TARGETS.items():
        source_dir = source_root / "prebuilt" / upstream_name
        if not source_dir.is_dir():
            print(f"missing upstream prebuilt dir: {source_dir}", flush=True)
            continue
        materialize_git_lfs_libraries(
            source_dir,
            upstream_tag=upstream_tag,
            source_root=source_root,
            suffixes=LIB_SUFFIXES,
        )
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def apply_prebuilt_override(override: PrebuiltOverride) -> None:
    target = BIN_DIR / override.platform / override.arch / override.filename
    staged = target.with_name(f"{target.name}.override")
    staged.unlink(missing_ok=True)
    url = (
        f"{UPSTREAM_MEDIA_BASE_URL}/{override.source_commit}/"
        f"{override.source_path}"
    )
    try:
        download_to_path(
            url,
            staged,
            headers={"User-Agent": "litert-lm-native-prebuilt-override"},
            label=(
                f"{override.source_path} at "
                f"{override.source_commit}"
            ),
        )
        actual = sha256_file(staged)
        if actual != override.sha256:
            raise RuntimeError(
                f"Prebuilt override checksum mismatch for {override.source_path}: "
                f"expected {override.sha256}, got {actual}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)


def apply_prebuilt_overrides(
    upstream_tag: str,
    *,
    platform: str | None = None,
    arch: str | None = None,
) -> int:
    overrides = tuple(
        override
        for override in prebuilt_overrides(upstream_tag)
        if (platform is None or override.platform == platform)
        and (arch is None or override.arch == arch)
    )
    for override in overrides:
        print(
            "Applying pinned prebuilt override: "
            f"{override.source_path} @ {override.source_commit}",
            flush=True,
        )
        apply_prebuilt_override(override)
    return len(overrides)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy upstream LiteRT-LM prebuilt runtime libs into bin/."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--clean", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--skip-overrides", action="store_true")
    mode.add_argument("--overrides-only", action="store_true")
    args = parser.parse_args()

    if args.overrides_only:
        if args.source_root is not None or args.clean:
            parser.error(
                "--overrides-only cannot be combined with --source-root or --clean"
            )
        copied = 0
    else:
        if args.source_root is not None:
            source_root = args.source_root
            if not source_root.is_dir():
                raise SystemExit(f"source root does not exist: {source_root}")
            copied = copy_prebuilts(
                source_root,
                upstream_tag=args.upstream_tag,
                clean=args.clean,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="litert-lm-native-") as temp:
                temp_dir = Path(temp)
                archive = temp_dir / f"LiteRT-LM-{args.upstream_tag}.tar.gz"
                download_source(args.upstream_tag, archive)
                source_root = extract_source(archive, temp_dir / "src")
                copied = copy_prebuilts(
                    source_root,
                    upstream_tag=args.upstream_tag,
                    clean=args.clean,
                )

    overridden = (
        0 if args.skip_overrides else apply_prebuilt_overrides(args.upstream_tag)
    )
    print(
        f"Copied {copied} upstream prebuilt libraries; "
        f"applied {overridden} pinned overrides",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
