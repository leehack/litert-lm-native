#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from fetch_litert_lm_asr_smoke_assets import ASSETS
from litert_lm_symbols import has_asr_bridge, is_at_least, uses_stream_chunk_api
from prebuilt_overrides import prebuilt_override_manifest
from release_version_policy import PolicyError, parse_upstream, validate_pair
from validate_runtime_artifacts import required_runtime_artifacts


REQUIRED_RUNTIME_ARCHIVES = [
    "litert-lm-native-runtime-android-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-android-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-ios-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-ios-arm64-sim-{tag}.tar.gz",
    "litert-lm-native-runtime-linux-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-linux-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-macos-arm64-{tag}.tar.gz",
    "litert-lm-native-runtime-macos-x64-{tag}.tar.gz",
    "litert-lm-native-runtime-windows-x64-{tag}.tar.gz",
]

REQUIRED_SPM_XCFRAMEWORKS = [
    "litert-lm-native-apple-CLiteRTLM-xcframework-{tag}.zip",
    "litert-lm-native-apple-CLiteRTLMMac-xcframework-{tag}.zip",
    "litert-lm-native-apple-LiteRtLm-xcframework-{tag}.zip",
]

V0_16_IOS_GPU_SPM_XCFRAMEWORKS = [
    "litert-lm-native-apple-LiteRtMetalAccelerator-xcframework-{tag}.zip",
    "litert-lm-native-apple-LiteRtTopKMetalSampler-xcframework-{tag}.zip",
]

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_PLATFORM_KEYS = {
    ("android", "arm64"),
    ("android", "x64"),
    ("ios", "arm64"),
    ("ios", "arm64-sim"),
    ("linux", "arm64"),
    ("linux", "x64"),
    ("macos", "arm64"),
    ("macos", "x64"),
    ("windows", "x64"),
}


def _validated_release_identity(
    *,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    release_tag: str,
):
    try:
        identity = parse_upstream(
            upstream_tag=upstream_tag,
            upstream_commit=upstream_commit,
            compatibility_tag=compatibility_tag,
        )
        return validate_pair(identity, release_tag)
    except PolicyError as error:
        raise SystemExit(f"Release identity is invalid: {error}") from error
ALLOWED_ACCELERATORS = {"gpu", "metal", "opencl", "webgpu"}


def _require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise SystemExit(
            f"{label} keys do not match schema 2; missing={missing}, "
            f"unexpected={unexpected}"
        )


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise SystemExit(f"{label} must be a lowercase 64-hex SHA-256 digest")
    return value


def _require_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{label} must be a non-empty repository-relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise SystemExit(f"{label} must be a safe normalized repository-relative path")
    return value


def validate_schema_2_payload(
    manifest: dict,
    *,
    upstream_tag: str | None,
    upstream_commit: str,
    compatibility_tag: str,
    native_commit: str,
    release_tag: str,
) -> None:
    """Validate the complete, finalized schema-2 owner contract fail closed."""
    _require_exact_keys(
        manifest,
        {
            "schemaVersion",
            "package",
            "release",
            "upstream",
            "native",
            "abi",
            "capabilities",
            "platforms",
            "artifacts",
            "realModelSmokes",
        },
        "manifest",
    )
    if manifest.get("schemaVersion") != 2:
        raise SystemExit("Release manifest schemaVersion must be 2")
    if manifest.get("package") != "litert-lm-native":
        raise SystemExit("Release manifest package must be litert-lm-native")

    release = manifest["release"]
    upstream = manifest["upstream"]
    native = manifest["native"]
    abi = manifest["abi"]
    capabilities = manifest["capabilities"]
    for value, label in (
        (release, "release"),
        (upstream, "upstream"),
        (native, "native"),
        (abi, "abi"),
        (capabilities, "capabilities"),
    ):
        if not isinstance(value, dict):
            raise SystemExit(f"Release manifest {label} must be an object")
    _require_exact_keys(
        release,
        {"tag", "channel", "kind", "rebuild", "githubPrerelease"},
        "release",
    )
    _require_exact_keys(
        upstream,
        {
            "repository",
            "tag",
            "commit",
            "compatibilityTag",
            "developmentIdentity",
            "prebuiltOverrides",
        },
        "upstream",
    )
    _require_exact_keys(native, {"repository", "commit"}, "native")
    _require_exact_keys(
        abi,
        {"upstreamC", "streamProxyCallback", "asrBridge"},
        "abi",
    )
    _require_exact_keys(
        capabilities,
        {
            "textGeneration",
            "streaming",
            "streamChunkAccessors",
            "asr",
            "officialUpstreamAssets",
        },
        "capabilities",
    )
    if upstream.get("repository") != "google-ai-edge/LiteRT-LM":
        raise SystemExit("Release manifest has an unexpected upstream repository")
    if native.get("repository") != "leehack/litert-lm-native":
        raise SystemExit("Release manifest has an unexpected native repository")
    if upstream.get("tag") != upstream_tag:
        raise SystemExit("Release manifest upstream tag does not match exact input")
    if upstream.get("commit") != upstream_commit or not FULL_SHA_RE.fullmatch(
        str(upstream.get("commit", ""))
    ):
        raise SystemExit("Release manifest upstream commit does not match exact input")
    if upstream.get("compatibilityTag") != compatibility_tag:
        raise SystemExit("Release manifest compatibility tag does not match exact input")
    if upstream.get("developmentIdentity") != f"g{upstream_commit[:12]}":
        raise SystemExit("Release manifest development identity is invalid")
    if upstream.get("prebuiltOverrides") != prebuilt_override_manifest(
        compatibility_tag
    ):
        raise SystemExit("Release manifest prebuilt override provenance is invalid")
    if native.get("commit") != native_commit or not FULL_SHA_RE.fullmatch(
        str(native.get("commit", ""))
    ):
        raise SystemExit("Release manifest native commit does not match exact input")

    parsed_release = _validated_release_identity(
        upstream_tag=upstream_tag,
        upstream_commit=upstream_commit,
        compatibility_tag=compatibility_tag,
        release_tag=release_tag,
    )
    expected_release = {
        "tag": release_tag,
        "channel": parsed_release.channel,
        "kind": parsed_release.kind,
        "rebuild": parsed_release.rebuild,
        "githubPrerelease": parsed_release.github_prerelease,
    }
    if release != expected_release:
        raise SystemExit("Release manifest release identity is incomplete or inconsistent")

    expected_asr = 1 if has_asr_bridge(compatibility_tag) else None
    expected_abi = {
        "upstreamC": "c/engine.h",
        "streamProxyCallback": 1,
        "asrBridge": expected_asr,
    }
    if abi != expected_abi:
        raise SystemExit("Release manifest ABI declaration is incomplete or inconsistent")
    expected_capabilities = {
        "textGeneration": True,
        "streaming": True,
        "streamChunkAccessors": uses_stream_chunk_api(compatibility_tag),
        "asr": has_asr_bridge(compatibility_tag),
        "officialUpstreamAssets": upstream_tag is not None,
    }
    if capabilities != expected_capabilities:
        raise SystemExit(
            "Release manifest capability declaration is incomplete or inconsistent"
        )

    platforms = manifest.get("platforms")
    if not isinstance(platforms, list) or len(platforms) != len(
        REQUIRED_PLATFORM_KEYS
    ):
        raise SystemExit("Release manifest must contain exactly nine platform bundles")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise SystemExit("Release manifest must contain provenance-bearing artifacts")

    artifacts_by_path: dict[str, dict] = {}
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise SystemExit(f"artifact[{index}] must be an object")
        _require_exact_keys(
            artifact,
            {
                "runtime",
                "platform",
                "arch",
                "path",
                "fileName",
                "sha256",
                "upstreamTag",
                "upstreamCommit",
                "releaseTag",
                "accelerators",
            },
            f"artifact[{index}]",
        )
        path = _require_relative_path(artifact.get("path"), f"artifact[{index}].path")
        if path in artifacts_by_path:
            raise SystemExit(f"Duplicate artifact path {path}")
        if artifact.get("fileName") != Path(path).name:
            raise SystemExit(f"artifact[{index}] fileName does not match path")
        _require_digest(artifact.get("sha256"), f"artifact[{index}].sha256")
        if artifact.get("upstreamTag") != upstream_tag:
            raise SystemExit(f"artifact[{index}] upstream tag provenance mismatch")
        if artifact.get("upstreamCommit") != upstream_commit:
            raise SystemExit(f"artifact[{index}] upstream commit provenance mismatch")
        if artifact.get("releaseTag") != release_tag:
            raise SystemExit(f"artifact[{index}] release tag provenance mismatch")
        runtime = artifact.get("runtime")
        if not isinstance(runtime, str) or runtime not in {
            "native",
            "archive",
            "web",
        }:
            raise SystemExit(f"artifact[{index}] has an invalid runtime family")
        accelerators = artifact.get("accelerators")
        if not isinstance(accelerators, list) or any(
            not isinstance(item, str) or not item for item in accelerators
        ) or len(accelerators) != len(set(accelerators)) or not set(
            accelerators
        ).issubset(ALLOWED_ACCELERATORS):
            raise SystemExit(
                f"artifact[{index}] accelerators must be unique allowed values"
            )
        artifacts_by_path[path] = artifact

    for override in upstream["prebuiltOverrides"]:
        target = artifacts_by_path.get(override["targetPath"])
        if (
            target is None
            or target.get("runtime") != "native"
            or target.get("sha256") != override["sha256"]
        ):
            raise SystemExit(
                "Release manifest prebuilt override target provenance is invalid"
            )

    seen_platforms: set[tuple[str, str]] = set()
    covered_paths: set[str] = set()
    for index, platform in enumerate(platforms):
        if not isinstance(platform, dict):
            raise SystemExit(f"platform[{index}] must be an object")
        _require_exact_keys(
            platform,
            {"platform", "arch", "releaseAsset", "artifactPaths", "accelerators"},
            f"platform[{index}]",
        )
        platform_name = platform.get("platform")
        arch = platform.get("arch")
        if (
            not isinstance(platform_name, str)
            or not platform_name
            or not isinstance(arch, str)
            or not arch
        ):
            raise SystemExit(f"platform[{index}] platform and arch must be strings")
        key = (platform_name, arch)
        if key not in REQUIRED_PLATFORM_KEYS or key in seen_platforms:
            raise SystemExit(f"platform[{index}] is missing, duplicate, or unsupported")
        seen_platforms.add(key)
        expected_asset = f"litert-lm-native-runtime-{key[0]}-{key[1]}-{release_tag}.tar.gz"
        if platform.get("releaseAsset") != expected_asset:
            raise SystemExit(f"platform[{index}] release asset does not match identity")
        paths = platform.get("artifactPaths")
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(path, str) for path in paths)
        ):
            raise SystemExit(f"platform[{index}] must contain unique artifact paths")
        for path_index, path in enumerate(paths):
            _require_relative_path(path, f"platform[{index}].artifactPaths[{path_index}]")
        if len(paths) != len(set(paths)):
            raise SystemExit(f"platform[{index}] must contain unique artifact paths")
        for path in paths:
            if path not in artifacts_by_path:
                raise SystemExit(f"platform[{index}] references an unknown artifact")
            artifact = artifacts_by_path[path]
            if artifact.get("runtime") != "native" or (
                artifact.get("platform"), artifact.get("arch")
            ) != key:
                raise SystemExit(f"platform[{index}] artifact provenance mismatch")
            covered_paths.add(path)
        accelerators = platform.get("accelerators")
        if (
            not isinstance(accelerators, list)
            or any(not isinstance(accelerator, str) for accelerator in accelerators)
            or len(accelerators) != len(set(accelerators))
            or not set(accelerators).issubset(ALLOWED_ACCELERATORS)
        ):
            raise SystemExit(
                f"platform[{index}] accelerators must be unique allowed strings"
            )
        linked_accelerators = sorted(
            {
                accelerator
                for path in paths
                for accelerator in artifacts_by_path[path]["accelerators"]
            }
        )
        if accelerators != linked_accelerators:
            raise SystemExit(
                f"platform[{index}] accelerators do not match linked artifacts"
            )
    if seen_platforms != REQUIRED_PLATFORM_KEYS:
        raise SystemExit("Release manifest is missing required platform bundles")
    native_paths = {
        path
        for path, artifact in artifacts_by_path.items()
        if artifact.get("runtime") == "native"
    }
    if covered_paths != native_paths:
        raise SystemExit("Release manifest has unbound native artifact provenance")

    required_paths = required_runtime_artifacts(
        compatibility_tag, include_official_assets=upstream_tag is not None
    )
    required_paths.extend(
        Path("dist") / "spm" / release_tag / asset.format(tag=release_tag)
        for asset in required_spm_assets(compatibility_tag)
    )
    platform_paths = {
        (platform["platform"], platform["arch"]): set(platform["artifactPaths"])
        for platform in platforms
    }
    for required_path in required_paths:
        path = required_path.as_posix()
        artifact = artifacts_by_path.get(path)
        if artifact is None:
            raise SystemExit(f"Release manifest is missing required runtime path {path}")
        if required_path.parts[0] == "bin":
            expected_platform, expected_arch = required_path.parts[1:3]
            if (
                artifact.get("runtime") != "native"
                or artifact.get("platform") != expected_platform
                or artifact.get("arch") != expected_arch
                or path not in platform_paths[(expected_platform, expected_arch)]
            ):
                raise SystemExit(
                    f"Required runtime path {path} has invalid runtime/platform/arch binding"
                )
        elif (
            artifact.get("runtime") != "archive"
            or artifact.get("platform") is not None
            or artifact.get("arch") is not None
        ):
            raise SystemExit(
                f"Required archive path {path} has invalid runtime/platform/arch binding"
            )

    smokes = manifest.get("realModelSmokes")
    if not isinstance(smokes, list):
        raise SystemExit("Release manifest realModelSmokes must be a list")
    seen_smokes: set[tuple[str, str, str]] = set()
    pinned_smoke_assets = {asset.filename: asset for asset in ASSETS}
    pinned_filenames = {
        "model": "moonshine_tiny_5s_i8.tflite",
        "tokenizer": "moonshine_tokenizer.json",
        "fixture": "jfk.wav",
    }
    missing_pinned_assets = sorted(
        set(pinned_filenames.values()).difference(pinned_smoke_assets)
    )
    if missing_pinned_assets:
        raise SystemExit(
            "Pinned smoke asset configuration is incomplete: "
            + ", ".join(missing_pinned_assets)
        )
    pinned_by_field = {
        field: pinned_smoke_assets[filename]
        for field, filename in pinned_filenames.items()
    }
    for index, smoke in enumerate(smokes):
        if not isinstance(smoke, dict):
            raise SystemExit(f"smoke[{index}] must be an object")
        _require_exact_keys(
            smoke,
            {
                "id",
                "result",
                "platform",
                "arch",
                "backend",
                "upstreamCommit",
                "nativeCommit",
                "abiVersion",
                "library",
                "model",
                "tokenizer",
                "fixture",
                "source",
                "expectation",
                "transcript",
            },
            f"smoke[{index}]",
        )
        key = (str(smoke.get("id")), str(smoke.get("platform")), str(smoke.get("arch")))
        if key in seen_smokes or (key[1], key[2]) not in REQUIRED_PLATFORM_KEYS:
            raise SystemExit(f"smoke[{index}] has a duplicate or unsupported identity")
        seen_smokes.add(key)
        if smoke.get("id") != "litert_lm_asr_moonshine" or smoke.get("result") != "pass":
            raise SystemExit(f"smoke[{index}] is not the required passing real-model smoke")
        if smoke.get("backend") != "cpu" or smoke.get("abiVersion") != 1:
            raise SystemExit(f"smoke[{index}] has invalid backend or ABI evidence")
        if smoke.get("upstreamCommit") != upstream_commit or smoke.get("nativeCommit") != native_commit:
            raise SystemExit(f"smoke[{index}] source commits do not match manifest")
        for field, expected_keys in (
            ("library", {"fileName", "sha256"}),
            ("model", {"fileName", "sha256"}),
            ("tokenizer", {"fileName", "sha256"}),
            ("fixture", {"fileName", "sha256", "sampleRateHz", "sampleCount"}),
        ):
            payload = smoke.get(field)
            if not isinstance(payload, dict):
                raise SystemExit(f"smoke[{index}].{field} must be an object")
            _require_exact_keys(payload, expected_keys, f"smoke[{index}].{field}")
            if not isinstance(payload.get("fileName"), str) or not payload["fileName"]:
                raise SystemExit(f"smoke[{index}].{field} is missing file identity")
            _require_digest(payload.get("sha256"), f"smoke[{index}].{field}.sha256")
        fixture = smoke["fixture"]
        if fixture.get("sampleRateHz") != 16000 or not isinstance(
            fixture.get("sampleCount"), int
        ) or fixture["sampleCount"] <= 0:
            raise SystemExit(f"smoke[{index}] has invalid fixture metadata")
        for field, pinned in pinned_by_field.items():
            payload = smoke[field]
            if (
                payload.get("fileName") != pinned.filename
                or payload.get("sha256") != pinned.sha256
            ):
                raise SystemExit(
                    f"smoke[{index}] {field} does not match the pinned smoke asset"
                )
        library = smoke["library"]
        matching_libraries = [
            artifact
            for artifact in artifacts_by_path.values()
            if artifact.get("runtime") == "native"
            and artifact.get("platform") == key[1]
            and artifact.get("arch") == key[2]
            and artifact.get("fileName") == library.get("fileName")
            and artifact.get("sha256") == library.get("sha256")
        ]
        if len(matching_libraries) != 1:
            raise SystemExit(
                f"smoke[{index}] library does not match one packaged runtime artifact"
            )
        source = smoke.get("source")
        if not isinstance(source, dict):
            raise SystemExit(f"smoke[{index}] is missing immutable source provenance")
        _require_exact_keys(
            source,
            {"runtimeReleaseAsset", "model", "tokenizer", "fixture"},
            f"smoke[{index}].source",
        )
        expected_asset = f"litert-lm-native-runtime-{key[1]}-{key[2]}-{release_tag}.tar.gz"
        if source.get("runtimeReleaseAsset") != expected_asset or any(
            source.get(field) != pinned_by_field[field].url
            for field in ("model", "tokenizer", "fixture")
        ):
            raise SystemExit(f"smoke[{index}] has invalid immutable source provenance")
        expectation = smoke.get("expectation")
        if not isinstance(expectation, dict):
            raise SystemExit(f"smoke[{index}] is missing transcript expectation")
        _require_exact_keys(expectation, {"type", "value"}, f"smoke[{index}].expectation")
        expected_text = expectation.get("value")
        transcript = smoke.get("transcript")
        if expectation != {
            "type": "case-insensitive-substring",
            "value": "country",
        } or not isinstance(transcript, str) or (
            expected_text.casefold() not in transcript.casefold()
        ):
            raise SystemExit(
                f"smoke[{index}] does not satisfy the pinned transcript expectation"
            )


def required_spm_assets(compatibility_tag: str) -> list[str]:
    assets = list(REQUIRED_SPM_XCFRAMEWORKS)
    if is_at_least(compatibility_tag, (0, 16, 0)):
        assets.extend(V0_16_IOS_GPU_SPM_XCFRAMEWORKS)
    return assets


def validate_schema_2_identity(
    manifest: dict,
    *,
    upstream_tag: str | None,
    upstream_commit: str | None,
    compatibility_tag: str | None,
    native_commit: str | None,
    release_tag: str,
) -> tuple[str, bool]:
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict):
        raise SystemExit("Release manifest is missing upstream provenance")
    if upstream.get("tag") != upstream_tag:
        raise SystemExit(
            "Release manifest upstream tag mismatch: "
            f"expected {upstream_tag}, got {upstream.get('tag')}"
        )
    manifest_upstream_commit = upstream.get("commit")
    if not isinstance(manifest_upstream_commit, str) or not FULL_SHA_RE.fullmatch(
        manifest_upstream_commit
    ):
        raise SystemExit("Release manifest upstream commit must be a full SHA")
    if upstream_commit and manifest_upstream_commit != upstream_commit:
        raise SystemExit(
            "Release manifest upstream commit mismatch: "
            f"expected {upstream_commit}, got {manifest_upstream_commit}"
        )
    manifest_compatibility = upstream.get("compatibilityTag")
    if not isinstance(manifest_compatibility, str):
        raise SystemExit("Release manifest is missing compatibilityTag")
    if compatibility_tag and manifest_compatibility != compatibility_tag:
        raise SystemExit(
            "Release manifest compatibility tag mismatch: "
            f"expected {compatibility_tag}, got {manifest_compatibility}"
        )

    native = manifest.get("native")
    if not isinstance(native, dict):
        raise SystemExit("Release manifest is missing native provenance")
    manifest_native_commit = native.get("commit")
    if not isinstance(manifest_native_commit, str) or not FULL_SHA_RE.fullmatch(
        manifest_native_commit
    ):
        raise SystemExit("Release manifest native commit must be a full SHA")
    if native_commit and manifest_native_commit != native_commit:
        raise SystemExit(
            "Release manifest native commit mismatch: "
            f"expected {native_commit}, got {manifest_native_commit}"
        )

    release = manifest.get("release")
    if not isinstance(release, dict) or release.get("tag") != release_tag:
        actual = release.get("tag") if isinstance(release, dict) else None
        raise SystemExit(
            "Release manifest native release tag mismatch: "
            f"expected {release_tag}, got {actual}"
        )
    parsed_release = _validated_release_identity(
        upstream_tag=upstream_tag,
        upstream_commit=manifest_upstream_commit,
        compatibility_tag=manifest_compatibility,
        release_tag=release_tag,
    )
    if release.get("channel") != parsed_release.channel:
        raise SystemExit("Release manifest channel does not match release tag")
    if release.get("kind") != parsed_release.kind:
        raise SystemExit("Release manifest kind does not match release tag")
    if release.get("rebuild") != parsed_release.rebuild:
        raise SystemExit("Release manifest rebuild does not match release tag")

    expected_overrides = prebuilt_override_manifest(manifest_compatibility)
    if upstream.get("prebuiltOverrides", []) != expected_overrides:
        raise SystemExit(
            "Release manifest prebuilt override provenance mismatch: "
            f"expected {expected_overrides}, got {upstream.get('prebuiltOverrides')}"
        )
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        raise SystemExit("Release manifest is missing capabilities")
    official_assets = capabilities.get("officialUpstreamAssets") is True
    if upstream_tag is not None and not official_assets:
        raise SystemExit("Stable releases must include official upstream assets")
    return manifest_compatibility, official_assets


def validate_legacy_identity(
    manifest: dict, *, upstream_tag: str | None, release_tag: str
) -> tuple[str, bool]:
    if upstream_tag is None:
        raise SystemExit("Legacy schema 1 manifests require --upstream-tag")
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict) or upstream.get("tag") != upstream_tag:
        actual = upstream.get("tag") if isinstance(upstream, dict) else None
        raise SystemExit(
            "Release manifest upstream tag mismatch: "
            f"expected {upstream_tag}, got {actual}"
        )
    release = manifest.get("release")
    if not isinstance(release, dict) or release.get("tag") != release_tag:
        actual = release.get("tag") if isinstance(release, dict) else None
        raise SystemExit(
            "Release manifest native release tag mismatch: "
            f"expected {release_tag}, got {actual}"
        )
    expected_overrides = prebuilt_override_manifest(upstream_tag)
    if upstream.get("prebuiltOverrides", []) != expected_overrides:
        raise SystemExit("Legacy manifest prebuilt override provenance mismatch")
    return upstream_tag, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate release manifest identity, payload, and evidence."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--upstream-tag", default="")
    parser.add_argument("--upstream-commit")
    parser.add_argument("--compatibility-tag")
    parser.add_argument("--native-commit")
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--release-metadata", type=Path)
    parser.add_argument(
        "--require-smoke",
        action="append",
        default=[],
        metavar="PLATFORM/ARCH",
    )
    args = parser.parse_args()
    upstream_tag = args.upstream_tag or None

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"Release manifest must be valid UTF-8 JSON: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise SystemExit("Release manifest must be a JSON object")
    schema_version = manifest.get("schemaVersion")
    if schema_version == 2:
        compatibility_tag, official_assets = validate_schema_2_identity(
            manifest,
            upstream_tag=upstream_tag,
            upstream_commit=args.upstream_commit,
            compatibility_tag=args.compatibility_tag,
            native_commit=args.native_commit,
            release_tag=args.release_tag,
        )
        validate_schema_2_payload(
            manifest,
            upstream_tag=upstream_tag,
            upstream_commit=str(manifest["upstream"]["commit"]),
            compatibility_tag=compatibility_tag,
            native_commit=str(manifest["native"]["commit"]),
            release_tag=args.release_tag,
        )
    elif schema_version == 1:
        compatibility_tag, official_assets = validate_legacy_identity(
            manifest, upstream_tag=upstream_tag, release_tag=args.release_tag
        )
    else:
        raise SystemExit(f"Unsupported release manifest schemaVersion {schema_version}")

    paths = {
        artifact.get("path")
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    }
    required = [
        path.as_posix()
        for path in required_runtime_artifacts(
            compatibility_tag, include_official_assets=official_assets
        )
    ]
    required_spm = required_spm_assets(compatibility_tag)
    required.extend(
        f"dist/spm/{args.release_tag}/{asset.format(tag=args.release_tag)}"
        for asset in required_spm
    )
    missing = [path for path in required if path not in paths]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"Release manifest is missing required runtime paths:\n{formatted}")

    smokes = manifest.get("realModelSmokes", [])
    if not isinstance(smokes, list):
        raise SystemExit("Release manifest realModelSmokes must be a list")
    passed_smokes = {
        f"{smoke.get('platform')}/{smoke.get('arch')}"
        for smoke in smokes
        if isinstance(smoke, dict) and smoke.get("result") == "pass"
    }
    missing_smokes = sorted(set(args.require_smoke) - passed_smokes)
    if missing_smokes:
        raise SystemExit(
            "Release manifest is missing required real-model smoke evidence: "
            + ", ".join(missing_smokes)
        )
    print(
        f"Release manifest lists {len(required)} required runtime artifacts and "
        f"{len(passed_smokes)} passing smoke target(s)"
    )

    if args.release_metadata is not None:
        try:
            release_metadata = json.loads(
                args.release_metadata.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SystemExit(
                f"Release metadata must be valid UTF-8 JSON: {error}"
            ) from error
        if not isinstance(release_metadata, dict):
            raise SystemExit("Release metadata must be a JSON object")
        release_assets = release_metadata.get("assets")
        if not isinstance(release_assets, list) or any(
            not isinstance(asset, dict)
            or not isinstance(asset.get("name"), str)
            or not asset["name"]
            for asset in release_assets
        ):
            raise SystemExit("Release metadata asset inventory is invalid")
        asset_names = [asset["name"] for asset in release_assets]
        if len(asset_names) != len(set(asset_names)):
            raise SystemExit("Release metadata has duplicate assets")
        if schema_version == 2:
            for index, asset in enumerate(release_assets):
                digest = asset.get("digest")
                if (
                    not isinstance(digest, str)
                    or not digest.startswith("sha256:")
                    or SHA256_RE.fullmatch(digest.removeprefix("sha256:")) is None
                ):
                    raise SystemExit(
                        f"release asset[{index}] must have an exact GitHub SHA-256 digest"
                    )
        asset_name_set = set(asset_names)
        spm_assets = sorted(
            Path(path).name
            for path in paths
            if isinstance(path, str)
            and path.startswith(f"dist/spm/{args.release_tag}/")
            and path.endswith(".zip")
        )
        required_assets = [
            "manifest.json",
            "SHA256SUMS",
            f"litert-lm-native-prebuilts-{args.release_tag}.tar.gz",
            *[
                pattern.format(tag=args.release_tag)
                for pattern in REQUIRED_RUNTIME_ARCHIVES
            ],
            *[pattern.format(tag=args.release_tag) for pattern in required_spm],
            *spm_assets,
        ]
        if schema_version == 2:
            required_assets.append("release-result.json")
        if official_assets:
            required_assets.append(
                f"litert-lm-native-official-assets-{args.release_tag}.tar.gz"
            )
        required_assets = sorted(set(required_assets))
        missing_assets = [
            asset for asset in required_assets if asset not in asset_name_set
        ]
        if missing_assets:
            formatted = "\n".join(f"- {asset}" for asset in missing_assets)
            raise SystemExit(f"Release is missing required assets:\n{formatted}")
        unexpected_assets = sorted(asset_name_set - set(required_assets))
        if unexpected_assets:
            formatted = "\n".join(f"- {asset}" for asset in unexpected_assets)
            raise SystemExit(f"Release has unexpected assets:\n{formatted}")
        print(f"Release metadata lists {len(required_assets)} required assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
