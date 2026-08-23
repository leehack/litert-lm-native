#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "manifest.json"
SHA256SUMS_PATH = REPO_ROOT / "SHA256SUMS"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"manifest.json must be valid UTF-8 JSON: {error}")
    if not isinstance(manifest, dict):
        fail("manifest.json must be a JSON object")
    schema_version = manifest.get("schemaVersion")
    if schema_version not in (1, 2):
        fail("manifest.json schemaVersion must be 1 or 2")
    if manifest.get("package") != "litert-lm-native":
        fail("manifest.json package must be litert-lm-native")
    if not isinstance(manifest.get("artifacts"), list):
        fail("manifest.json artifacts must be a list")
    if schema_version == 2:
        for section in (
            "release",
            "upstream",
            "native",
            "abi",
            "capabilities",
            "platforms",
            "realModelSmokes",
        ):
            if section not in manifest:
                fail(f"manifest.json schema 2 missing {section}")
        for section in ("upstream", "native"):
            if not isinstance(manifest[section], dict):
                fail(f"manifest.json schema 2 {section} must be an object")
        for label, commit in (
            ("upstream", manifest["upstream"].get("commit")),
            ("native", manifest["native"].get("commit")),
        ):
            if not isinstance(commit, str) or FULL_SHA_RE.fullmatch(commit) is None:
                fail(f"manifest.json {label} commit must be a lowercase 40-hex SHA")

    seen = set()
    for index, artifact in enumerate(manifest["artifacts"]):
        if not isinstance(artifact, dict):
            fail(f"artifact[{index}] must be an object")
        for key in ("runtime", "platform", "path", "fileName", "sha256"):
            if key not in artifact:
                fail(f"artifact[{index}] missing {key}")
        artifact_path = artifact["path"]
        relative_path = Path(artifact_path) if isinstance(artifact_path, str) else None
        if (
            relative_path is None
            or not artifact_path
            or "\\" in artifact_path
            or artifact_path == "."
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.as_posix() != artifact_path
        ):
            fail(
                f"artifact[{index}] path must be a safe normalized "
                "repository-relative path"
            )
        path = REPO_ROOT / relative_path
        if artifact_path in seen:
            fail(f"duplicate artifact path: {artifact_path}")
        seen.add(artifact_path)
        if not path.is_file():
            fail(f"artifact does not exist: {artifact_path}")
        if (
            not isinstance(artifact["sha256"], str)
            or SHA256_RE.fullmatch(artifact["sha256"]) is None
        ):
            fail(f"artifact[{index}] sha256 must be a 64-hex digest")
        actual = sha256_file(path)
        if actual != artifact["sha256"]:
            fail(f"checksum mismatch for {artifact_path}")
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
