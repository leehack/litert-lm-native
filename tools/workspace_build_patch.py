"""Identity of the carried v0.18.1 Bazel WORKSPACE build repair."""
import hashlib
import re
from pathlib import Path

PATCH_PATH = "native/bridge/v0181_workspace_build.patch"
# v0.18.1 took main's LiteRT/TensorFlow pin bump (RevId 996789227) without the
# WORKSPACE plumbing that TensorFlow a1179d3c needs, so its Bazel loading phase
# fails on `compatibility_proxy_repo`. The postimages are byte-identical to
# upstream main d99b438f, the same RevId with the same pins.
UPSTREAM_EQUIVALENT = "d99b438f0a961ac2a449d341c2431e49332c1076"
AUDITED_TAGS = frozenset({"v0.18.1"})
# v0.19.0 descends from UPSTREAM_EQUIVALENT and declares the same plumbing.
UPSTREAM_FIX_TAGS = frozenset({"v0.19.0"})
# LF-normalized (preimage, postimage) SHA-256 per patched v0.18.1 file.
SOURCES = {
    ".bazelrc": (
        "0f585dc62934562993848d588018cd5fd4a4e92ff8a01e17c31a5cd63820aa77",
        "b2143d38c990969a901d54055da9875142b895d64202afc5548e67a1adc3988e",
    ),
    "WORKSPACE": (
        "2dfa4a5a492b9b99be2e767b4573bc65f1c5268a502391755af22ca77ea0e88a",
        "f251c52a03dc229cdd18fb61a1aeaf0c4a625c487fd4598087832c59726dbb66",
    ),
}


def require_workspace_build_patch_decision(compatibility_tag: str) -> bool:
    """Returns whether the repair applies; newer sources need a decision."""
    if compatibility_tag in AUDITED_TAGS:
        return True
    if compatibility_tag in UPSTREAM_FIX_TAGS:
        return False
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) <= (0, 18, 0):
        return False
    raise RuntimeError(
        f"Bazel WORKSPACE build repair has no explicit decision for "
        f"{compatibility_tag}; revalidate the carried patch or record an "
        "upstream equivalent in tools/workspace_build_patch.py and "
        "docs/upstream_patch_audit.md")


def workspace_build_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_workspace_build_patch_decision(compatibility_tag):
        return []
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()
    ).hexdigest()
    return [{
        "id": "workspace-build",
        "path": PATCH_PATH,
        "sha256": patch_sha256,
        "source": source,
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for source, (preimage, postimage) in SOURCES.items()]
