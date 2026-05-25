#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "manifest.json"
SHA256SUMS_PATH = REPO_ROOT / "SHA256SUMS"


def fail(message: str) -> None:
    raise SystemExit(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        fail(f"Missing {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1:
        fail("manifest.json schemaVersion must be 1")
    if manifest.get("package") != "litert-lm-native":
        fail("manifest.json package must be litert-lm-native")
    if not isinstance(manifest.get("artifacts"), list):
        fail("manifest.json artifacts must be a list")

    seen = set()
    for index, artifact in enumerate(manifest["artifacts"]):
        for key in ("runtime", "platform", "path", "fileName", "sha256"):
            if key not in artifact:
                fail(f"artifact[{index}] missing {key}")
        path = REPO_ROOT / artifact["path"]
        if artifact["path"] in seen:
            fail(f"duplicate artifact path: {artifact['path']}")
        seen.add(artifact["path"])
        if not path.is_file():
            fail(f"artifact does not exist: {artifact['path']}")
        actual = sha256_file(path)
        if actual != artifact["sha256"]:
            fail(f"checksum mismatch for {artifact['path']}")
    return manifest


def validate_sha256sums(manifest: dict) -> None:
    if not SHA256SUMS_PATH.is_file():
        fail(f"Missing {SHA256SUMS_PATH}")
    expected = {
        artifact["path"]: artifact["sha256"] for artifact in manifest["artifacts"]
    }
    lines = [
        line.strip()
        for line in SHA256SUMS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actual = {}
    for line in lines:
        checksum, path = line.split(maxsplit=1)
        actual[path] = checksum
    if actual != expected:
        fail("SHA256SUMS does not match manifest artifacts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate release artifacts.")
    parser.parse_args()

    manifest = validate_manifest()
    validate_sha256sums(manifest)
    print(f"Validated {len(manifest['artifacts'])} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
