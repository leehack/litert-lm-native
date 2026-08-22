from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrebuiltOverride:
    upstream_target: str
    platform: str
    arch: str
    filename: str
    source_commit: str
    sha256: str

    @property
    def source_path(self) -> str:
        return f"prebuilt/{self.upstream_target}/{self.filename}"

    @property
    def target_path(self) -> str:
        return f"bin/{self.platform}/{self.arch}/{self.filename}"


UPSTREAM_REPOSITORY = "google-ai-edge/LiteRT-LM"
UPSTREAM_MEDIA_BASE_URL = (
    "https://media.githubusercontent.com/media/google-ai-edge/LiteRT-LM"
)

V0_15_ANDROID_SAMPLER_FIX_COMMIT = (
    "8bee4dddc3794958b4bdd8a3a4ba75bcb71f6fbb"
)
ANDROID_DAWN_ROLLBACK_COMMIT = (
    "f73637c57f0940b53da184e0d5adfc52a4e55eef"
)

ANDROID_DAWN_ROLLBACKS = (
    PrebuiltOverride(
        upstream_target="android_arm64",
        platform="android",
        arch="arm64",
        filename="libwebgpu_dawn.so",
        source_commit=ANDROID_DAWN_ROLLBACK_COMMIT,
        sha256=(
            "7282aacdb076ce89f0c9d93107a145b991b99eb1dfbd5b5746dd0d99466ab3c3"
        ),
    ),
    PrebuiltOverride(
        upstream_target="android_x86_64",
        platform="android",
        arch="x64",
        filename="libwebgpu_dawn.so",
        source_commit=ANDROID_DAWN_ROLLBACK_COMMIT,
        sha256=(
            "fcfb9a0b902f7dd3f81f01295f381c10b22a2d5774f95ee0db813f284a0ab087"
        ),
    ),
)

PREBUILT_OVERRIDES: dict[str, tuple[PrebuiltOverride, ...]] = {
    "v0.15.0": (
        PrebuiltOverride(
            upstream_target="android_arm64",
            platform="android",
            arch="arm64",
            filename="libLiteRtTopKOpenClSampler.so",
            source_commit=V0_15_ANDROID_SAMPLER_FIX_COMMIT,
            sha256=(
                "4404dc68786460602685cab62ddfa29035e9cfc38bb4550dec15abaaa1302a82"
            ),
        ),
        PrebuiltOverride(
            upstream_target="android_x86_64",
            platform="android",
            arch="x64",
            filename="libLiteRtTopKOpenClSampler.so",
            source_commit=V0_15_ANDROID_SAMPLER_FIX_COMMIT,
            sha256=(
                "747ca5ed6a175fb4c2854ccee1d6ad97f11fe14d9e0d2b0c1710e1435376d51e"
            ),
        ),
        *ANDROID_DAWN_ROLLBACKS,
    ),
    "v0.16.0": ANDROID_DAWN_ROLLBACKS,
    # v0.16.1 is a metadata-only release of the exact v0.16.0 source commit.
    # Development builds using it as their compatibility baseline keep the
    # validated Dawn correction until new device evidence retires it.
    "v0.16.1": ANDROID_DAWN_ROLLBACKS,
}


def prebuilt_overrides(upstream_tag: str | None) -> tuple[PrebuiltOverride, ...]:
    if upstream_tag is None:
        return ()
    return PREBUILT_OVERRIDES.get(upstream_tag, ())


def prebuilt_override_manifest(upstream_tag: str | None) -> list[dict[str, str]]:
    return [
        {
            "sourceRepository": UPSTREAM_REPOSITORY,
            "sourceCommit": override.source_commit,
            "sourcePath": override.source_path,
            "targetPath": override.target_path,
            "sha256": override.sha256,
        }
        for override in prebuilt_overrides(upstream_tag)
    ]
