#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
WEB_DIST_DIR = REPO_ROOT / "web" / "dist"
DIST_DIR = REPO_ROOT / "dist"
MANIFEST_PATH = REPO_ROOT / "manifest.json"
SHA256SUMS_PATH = REPO_ROOT / "SHA256SUMS"

NATIVE_EXTENSIONS = {
    ".so",
    ".dylib",
    ".dll",
    ".lib",
    ".a",
    ".framework",
    ".xcframework",
}
WEB_EXTENSIONS = {".js", ".mjs", ".cjs", ".wasm", ".json", ".data"}
ARCHIVE_SUFFIXES = (".zip", ".tgz", ".tar.gz")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_bin_metadata(path: Path) -> tuple[str, str | None, str | None]:
    relative = path.relative_to(BIN_DIR)
    parts = relative.parts
    platform = parts[0] if parts else None
    arch = parts[1] if len(parts) > 2 else None
    return "native", platform, arch


def iter_artifacts() -> list[Path]:
    artifacts: list[Path] = []
    if BIN_DIR.exists():
        for path in BIN_DIR.rglob("*"):
            if path.is_file() and path.suffix in NATIVE_EXTENSIONS:
                artifacts.append(path)
    if WEB_DIST_DIR.exists():
        for path in WEB_DIST_DIR.rglob("*"):
            if path.is_file() and path.suffix in WEB_EXTENSIONS:
                artifacts.append(path)
    if DIST_DIR.exists():
        for path in DIST_DIR.rglob("*"):
            if path.is_file() and path.name.endswith(ARCHIVE_SUFFIXES):
                artifacts.append(path)
    return sorted(artifacts)


def build_manifest(upstream_tag: str | None) -> dict:
    entries = []
    sums = []
    for path in iter_artifacts():
        if path.is_relative_to(BIN_DIR):
            runtime, platform, arch = infer_bin_metadata(path)
        elif path.is_relative_to(DIST_DIR):
            runtime, platform, arch = "archive", None, None
        else:
            runtime, platform, arch = "web", "web", None
        checksum = sha256_file(path)
        relative = path.relative_to(REPO_ROOT).as_posix()
        entries.append(
            {
                "runtime": runtime,
                "platform": platform,
                "arch": arch,
                "path": relative,
                "fileName": path.name,
                "sha256": checksum,
                "upstreamTag": upstream_tag,
                "accelerators": [],
            }
        )
        sums.append(f"{checksum}  {relative}")

    SHA256SUMS_PATH.write_text("\n".join(sums) + ("\n" if sums else ""), encoding="utf-8")
    return {
        "schemaVersion": 1,
        "package": "litert-lm-native",
        "upstream": {
            "repository": "google-ai-edge/LiteRT-LM",
            "tag": upstream_tag,
            "commit": None,
        },
        "artifacts": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate manifest and checksums.")
    parser.add_argument("--upstream-tag", default=None)
    args = parser.parse_args()

    manifest = build_manifest(args.upstream_tag)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {MANIFEST_PATH}")
    print(f"Wrote {SHA256SUMS_PATH}")
    print(f"Artifacts: {len(manifest['artifacts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
