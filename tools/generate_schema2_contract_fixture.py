#!/usr/bin/env python3
"""Generate the canonical owner-produced LiteRT-LM schema-2 contract fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import package_release
from fetch_litert_lm_asr_smoke_assets import ASSETS
from validate_release_manifest import required_spm_assets
from validate_runtime_artifacts import required_runtime_artifacts


UPSTREAM_COMMIT = "924e79c91542761242244e4f1651851f822e4cbb"
NATIVE_COMMIT = "451ba0ce7c366972b4dc0e58f08ffe590958f943"
UPSTREAM_TAG = "v0.16.0"
RELEASE_TAG = "v0.16.0-3"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _smoke(platform: str, arch: str) -> dict:
    sources = {asset.filename: asset.url for asset in ASSETS}
    return {
        "id": "litert_lm_asr_moonshine",
        "result": "pass",
        "platform": platform,
        "arch": arch,
        "backend": "cpu",
        "upstreamCommit": UPSTREAM_COMMIT,
        "nativeCommit": NATIVE_COMMIT,
        "abiVersion": 1,
        "library": {"fileName": "libLiteRtLm", "sha256": "1" * 64},
        "model": {
            "fileName": "moonshine_tiny_5s_i8.tflite",
            "sha256": "2" * 64,
        },
        "tokenizer": {
            "fileName": "moonshine_tokenizer.json",
            "sha256": "3" * 64,
        },
        "fixture": {
            "fileName": "jfk.wav",
            "sha256": "4" * 64,
            "sampleRateHz": 16000,
            "sampleCount": 176000,
        },
        "source": {
            "runtimeReleaseAsset": (
                f"litert-lm-native-runtime-{platform}-{arch}-{RELEASE_TAG}.tar.gz"
            ),
            "model": sources["moonshine_tiny_5s_i8.tflite"],
            "tokenizer": sources["moonshine_tokenizer.json"],
            "fixture": sources["jfk.wav"],
        },
        "expectation": {
            "type": "case-insensitive-substring",
            "value": "country",
        },
        "transcript": "ask not what your country can do for you",
    }


def generate_manifest() -> dict:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for relative in required_runtime_artifacts(
            UPSTREAM_TAG, include_official_assets=True
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"fixture:{relative.as_posix()}".encode())
        for asset in required_spm_assets(UPSTREAM_TAG):
            path = root / "dist" / "spm" / RELEASE_TAG / asset.format(
                tag=RELEASE_TAG
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"fixture:{path.name}".encode())

        evidence_dir = root / "evidence"
        evidence_dir.mkdir()
        for platform, arch in (("linux", "x64"), ("windows", "x64")):
            (evidence_dir / f"{platform}-{arch}.json").write_text(
                json.dumps(_smoke(platform, arch)), encoding="utf-8"
            )

        original = (
            package_release.REPO_ROOT,
            package_release.BIN_DIR,
            package_release.WEB_DIST_DIR,
            package_release.DIST_DIR,
            package_release.SHA256SUMS_PATH,
        )
        try:
            package_release.REPO_ROOT = root
            package_release.BIN_DIR = root / "bin"
            package_release.WEB_DIST_DIR = root / "web" / "dist"
            package_release.DIST_DIR = root / "dist"
            package_release.SHA256SUMS_PATH = root / "SHA256SUMS"
            return package_release.build_manifest(
                upstream_tag=UPSTREAM_TAG,
                upstream_commit=UPSTREAM_COMMIT,
                compatibility_tag=UPSTREAM_TAG,
                release_tag=RELEASE_TAG,
                native_commit=NATIVE_COMMIT,
                evidence_dir=evidence_dir,
                official_upstream_assets=True,
            )
        finally:
            (
                package_release.REPO_ROOT,
                package_release.BIN_DIR,
                package_release.WEB_DIST_DIR,
                package_release.DIST_DIR,
                package_release.SHA256SUMS_PATH,
            ) = original


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output} ({_digest(args.output.read_bytes())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
