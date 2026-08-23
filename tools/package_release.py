#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from litert_lm_symbols import has_asr_bridge, uses_stream_chunk_api
from prebuilt_overrides import prebuilt_override_manifest
from release_version_policy import parse_upstream, validate_pair


REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
WEB_DIST_DIR = REPO_ROOT / "web" / "dist"
DIST_DIR = REPO_ROOT / "dist"
MANIFEST_PATH = REPO_ROOT / "manifest.json"
SHA256SUMS_PATH = REPO_ROOT / "SHA256SUMS"

NATIVE_FILE_EXTENSIONS = {".so", ".dylib", ".dll", ".lib", ".a", ".zip"}
NATIVE_BUNDLE_EXTENSIONS = {".framework", ".xcframework"}
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


def is_native_artifact(path: Path) -> bool:
    if path.suffix in NATIVE_FILE_EXTENSIONS:
        return True
    return any(Path(part).suffix in NATIVE_BUNDLE_EXTENSIONS for part in path.parts)


def iter_artifacts() -> list[Path]:
    artifacts: list[Path] = []
    if BIN_DIR.exists():
        artifacts.extend(
            path
            for path in BIN_DIR.rglob("*")
            if path.is_file() and is_native_artifact(path)
        )
    if WEB_DIST_DIR.exists():
        artifacts.extend(
            path
            for path in WEB_DIST_DIR.rglob("*")
            if path.is_file() and path.suffix in WEB_EXTENSIONS
        )
    if DIST_DIR.exists():
        artifacts.extend(
            path
            for path in DIST_DIR.rglob("*")
            if path.is_file() and path.name.endswith(ARCHIVE_SUFFIXES)
        )
    return sorted(artifacts)


def artifact_accelerators(path: Path) -> list[str]:
    name = path.name.casefold()
    accelerators: set[str] = set()
    if "opencl" in name:
        accelerators.add("opencl")
    if "metal" in name:
        accelerators.add("metal")
    if "webgpu" in name or "dawn" in name:
        accelerators.add("webgpu")
    if "gpu" in name and not accelerators:
        accelerators.add("gpu")
    return sorted(accelerators)


def current_native_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.PIPE,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise ValueError(
            "could not determine the native commit with "
            f"git rev-parse HEAD: {str(detail).strip()}"
        ) from error


def load_smoke_evidence(
    evidence_dir: Path | None,
    *,
    upstream_commit: str,
    native_commit: str,
    release_tag: str,
) -> list[dict]:
    if evidence_dir is None:
        return []
    if evidence_dir.is_symlink():
        raise ValueError(
            "smoke evidence directory must be a non-symlink directory: "
            f"{evidence_dir}"
        )
    if not evidence_dir.exists():
        return []
    if not evidence_dir.is_dir():
        raise ValueError(
            "smoke evidence directory must be a non-symlink directory: "
            f"{evidence_dir}"
        )
    try:
        evidence_root = evidence_dir.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"smoke evidence directory is unavailable: {error}") from error
    evidence: list[dict] = []
    identities: set[tuple[str, str, str]] = set()
    for path in sorted(evidence_dir.rglob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                f"smoke evidence must be a regular non-symlink file: {path}"
            )
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"smoke evidence path is unavailable: {path}: {error}") from error
        try:
            resolved.relative_to(evidence_root)
        except ValueError as error:
            raise ValueError(
                f"smoke evidence must remain inside its evidence directory: {path}"
            ) from error
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                f"smoke evidence must be valid UTF-8 JSON: {path}: {error}"
            ) from error
        if not isinstance(item, dict):
            raise ValueError(f"smoke evidence must be an object: {path}")
        if item.get("result") != "pass":
            raise ValueError(f"smoke evidence is not a pass: {path}")
        if item.get("upstreamCommit") != upstream_commit:
            raise ValueError(f"smoke evidence upstream commit mismatch: {path}")
        if item.get("nativeCommit") != native_commit:
            raise ValueError(f"smoke evidence native commit mismatch: {path}")
        if item.get("id") != "litert_lm_asr_moonshine":
            raise ValueError(f"unexpected smoke evidence id: {path}")
        if item.get("backend") != "cpu" or item.get("abiVersion") != 1:
            raise ValueError(f"invalid smoke backend or ABI evidence: {path}")
        for field in ("library", "model", "tokenizer", "fixture"):
            payload = item.get(field)
            digest = payload.get("sha256") if isinstance(payload, dict) else None
            if not isinstance(digest, str) or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError(f"invalid {field} digest in smoke evidence: {path}")
        source = item.get("source")
        if not isinstance(source, dict) or any(
            not isinstance(source.get(field), str) or not source[field]
            for field in ("runtimeReleaseAsset", "model", "tokenizer", "fixture")
        ):
            raise ValueError(f"smoke evidence has no immutable source provenance: {path}")
        expected_runtime_asset = (
            "litert-lm-native-runtime-"
            f"{item.get('platform')}-{item.get('arch')}-{release_tag}.tar.gz"
        )
        if source.get("runtimeReleaseAsset") != expected_runtime_asset:
            raise ValueError(f"smoke evidence runtime source mismatch: {path}")
        expectation = item.get("expectation")
        if (
            not isinstance(expectation, dict)
            or expectation.get("type") != "case-insensitive-substring"
            or not isinstance(expectation.get("value"), str)
            or not expectation["value"].strip()
        ):
            raise ValueError(f"smoke evidence has no transcript expectation: {path}")
        if not isinstance(item.get("transcript"), str) or not item["transcript"].strip():
            raise ValueError(f"smoke evidence has no transcript: {path}")
        if expectation["value"].casefold() not in item["transcript"].casefold():
            raise ValueError(f"smoke evidence does not satisfy expectation: {path}")
        identity = (
            str(item.get("id", "")),
            str(item.get("platform", "")),
            str(item.get("arch", "")),
        )
        if not all(identity) or identity in identities:
            raise ValueError(f"invalid or duplicate smoke evidence identity: {path}")
        identities.add(identity)
        evidence.append(item)
    return evidence


def build_manifest(
    *,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    release_tag: str,
    native_commit: str,
    evidence_dir: Path | None = None,
    official_upstream_assets: bool = False,
) -> dict:
    upstream = parse_upstream(
        upstream_tag=upstream_tag,
        upstream_commit=upstream_commit,
        compatibility_tag=compatibility_tag,
    )
    release_identity = validate_pair(upstream, release_tag)
    expected_official_assets = upstream.channel == "stable"
    if official_upstream_assets != expected_official_assets:
        raise ValueError(
            "official_upstream_assets must be true for stable releases and false "
            "for development releases"
        )

    entries: list[dict] = []
    sums: list[str] = []
    platform_paths: dict[tuple[str, str], list[str]] = {}
    platform_accelerators: dict[tuple[str, str], set[str]] = {}
    for path in iter_artifacts():
        if path.is_relative_to(BIN_DIR):
            runtime, platform, arch = infer_bin_metadata(path)
        elif path.is_relative_to(DIST_DIR):
            runtime, platform, arch = "archive", None, None
        else:
            runtime, platform, arch = "web", "web", None
        checksum = sha256_file(path)
        relative = path.relative_to(REPO_ROOT).as_posix()
        accelerators = artifact_accelerators(path)
        entries.append(
            {
                "runtime": runtime,
                "platform": platform,
                "arch": arch,
                "path": relative,
                "fileName": path.name,
                "sha256": checksum,
                "upstreamTag": upstream_tag,
                "upstreamCommit": upstream_commit,
                "releaseTag": release_tag,
                "accelerators": accelerators,
            }
        )
        sums.append(f"{checksum}  {relative}")
        if runtime == "native" and platform and arch:
            key = (platform, arch)
            platform_paths.setdefault(key, []).append(relative)
            platform_accelerators.setdefault(key, set()).update(accelerators)

    smoke_evidence = load_smoke_evidence(
        evidence_dir,
        upstream_commit=upstream_commit,
        native_commit=native_commit,
        release_tag=release_tag,
    )
    platforms = [
        {
            "platform": platform,
            "arch": arch,
            "releaseAsset": (
                f"litert-lm-native-runtime-{platform}-{arch}-{release_tag}.tar.gz"
            ),
            "artifactPaths": sorted(platform_paths[(platform, arch)]),
            "accelerators": sorted(platform_accelerators[(platform, arch)]),
        }
        for platform, arch in sorted(platform_paths)
    ]

    SHA256SUMS_PATH.write_text(
        "\n".join(sums) + ("\n" if sums else ""), encoding="utf-8"
    )
    return {
        "schemaVersion": 2,
        "package": "litert-lm-native",
        "release": {
            "tag": release_tag,
            "channel": release_identity.channel,
            "kind": release_identity.kind,
            "rebuild": release_identity.rebuild,
            "githubPrerelease": release_identity.github_prerelease,
        },
        "upstream": {
            "repository": "google-ai-edge/LiteRT-LM",
            "tag": upstream_tag,
            "commit": upstream_commit,
            "compatibilityTag": compatibility_tag,
            "developmentIdentity": f"g{upstream_commit[:12]}",
            "prebuiltOverrides": prebuilt_override_manifest(compatibility_tag),
        },
        "native": {
            "repository": "leehack/litert-lm-native",
            "commit": native_commit,
        },
        "abi": {
            "upstreamC": "c/engine.h",
            "streamProxyCallback": 1,
            "asrBridge": 1 if has_asr_bridge(compatibility_tag) else None,
        },
        "capabilities": {
            "textGeneration": True,
            "streaming": True,
            "streamChunkAccessors": uses_stream_chunk_api(compatibility_tag),
            "asr": has_asr_bridge(compatibility_tag),
            "officialUpstreamAssets": official_upstream_assets,
        },
        "platforms": platforms,
        "artifacts": entries,
        "realModelSmokes": smoke_evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate manifest and checksums.")
    parser.add_argument("--upstream-tag", default="")
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--compatibility-tag", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--native-commit", default="")
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--official-upstream-assets", action="store_true")
    args = parser.parse_args()

    try:
        manifest = build_manifest(
            upstream_tag=args.upstream_tag or None,
            upstream_commit=args.upstream_commit,
            compatibility_tag=args.compatibility_tag,
            release_tag=args.release_tag,
            native_commit=args.native_commit or current_native_commit(),
            evidence_dir=args.evidence_dir,
            official_upstream_assets=args.official_upstream_assets,
        )
        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"Release manifest generation failed: {error}") from error
    print(f"Wrote {MANIFEST_PATH}")
    print(f"Wrote {SHA256SUMS_PATH}")
    print(f"Artifacts: {len(manifest['artifacts'])}")
    print(f"Real-model smokes: {len(manifest['realModelSmokes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
