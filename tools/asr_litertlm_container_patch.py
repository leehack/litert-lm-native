"""Identity of the carried v0.18 ASR `.litertlm` container routing backport."""
import hashlib
import re
from pathlib import Path

AUDITED_CONTAINER_TAGS = frozenset({"v0.18.0", "v0.18.1"})
PATCH_PATH = "native/bridge/asr_litertlm_container.patch"
# Upstream google-ai-edge/LiteRT-LM bfdec21732 ("Support ASR models in
# .litertlm") landed on main after the v0.18 release branch was cut.
UPSTREAM_FIX_COMMIT = "bfdec21732"
# LF-normalized (preimage, postimage) SHA-256 per patched v0.18.0 source.
SOURCES = {
    "omni/asr/BUILD": (
        "495b4b4821fc768ca2733bdb18a45a0f6aac300771f9b1f1fa7bf76c98ee9b97",
        "b19ed72004ed674549f48938613e1d03a8c1af322e9214aab7b37a37ab294c7e",
    ),
    "omni/asr/asr_engine.cc": (
        "96132de1f1d665d70585a2ef5ff64f5b432992c116f8f31b5f084679cc1f47d4",
        "b92d66fda41b5a995d8a8a1a83b86067b003392d4be53d6821928064e0fe1fd4",
    ),
    "omni/asr/asr_engine.h": (
        "ace689b9bf490bee06e740d5965a99ee402bb194ed4ee29d425f2e651e365cf3",
        "cdb5f862e6e0d46041de0c0a1f0bbff20e640258fab30a3d02ed519f3781dd4c",
    ),
}


def require_container_patch_decision(compatibility_tag: str) -> bool:
    """Returns whether the backport applies; newer sources need a decision."""
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) < (0, 18, 0):
        return False
    if compatibility_tag in AUDITED_CONTAINER_TAGS:
        return True
    raise RuntimeError(
        f"ASR .litertlm container routing has no explicit decision for "
        f"{compatibility_tag}; check for upstream {UPSTREAM_FIX_COMMIT}, then "
        "revalidate the carried patch or record its retirement in "
        "tools/asr_litertlm_container_patch.py and docs/upstream_patch_audit.md")


def container_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_container_patch_decision(compatibility_tag):
        return []
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()
    ).hexdigest()
    return [{
        "id": "asr-litertlm-container",
        "path": PATCH_PATH,
        "sha256": patch_sha256,
        "source": source,
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for source, (preimage, postimage) in SOURCES.items()]
