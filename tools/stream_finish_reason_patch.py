"""Identity of the carried stream finish-reason patch (#78)."""
import hashlib
import re
from pathlib import Path

PATCH_PATH = "native/bridge/stream_finish_reason.patch"
BAZEL_DEFINE = "--define=litert_lm_finish_reason_api=true"
# v0.18.1 changes dependencies only; all six preimages equal v0.18.0.
AUDITED_FINISH_REASON_TAGS = frozenset({"v0.18.0", "v0.18.1", "v0.19.0"})
# LF-normalized (preimage, postimage) SHA-256 per patched v0.18.0 source.
SOURCES = {
    "c/conversation.cc": (
        "17ad21e19c750c3216af7ca634dbbc58e8e0ca17445ce172fd607764b169cbf2",
        "60cd715a7d56e7f6b66a50b0d18f34a346f979fb09310835e1b1232a64a888ba",
    ),
    "c/engine_internal.h": (
        "7a4f6796238ab25547f2a2a791dddcede273e422e90837b18ae4fe277f522e49",
        "4df4517a4e9bfedcce915dd3ee394dff3813f9d89501122d97771d5ba8b19be6",
    ),
    "runtime/conversation/conversation.cc": (
        "f87825973603d8c53e8cb63ff12bbe5a8e907821bde4d48f4cbf5bf20f85888c",
        "b9a81c34f90ba75846f3beffc6ade99d3e2ae00e832a2793f6b2b086bb756098",
    ),
    "runtime/conversation/conversation.h": (
        "e86f23bb7c68f79966a581910aa9beda278d581dd74ad5a1c4733195eab2ae89",
        "4a2d7b70c0294a789a3190b07eda669bd497c8882e01a47d97b713b2acb2c48d",
    ),
    "runtime/core/tasks.cc": (
        "bd731f46d33272bbfc0f2ae4a951c7b042db58360403b902e0d08732a993134e",
        "05566017ac6af05f6093f4b9f760fc683f6fba461068a612430f1d9011f86c42",
    ),
    "runtime/engine/io_types.h": (
        "9475b9c9d22c18c93defbbe20d675fdd4a27bf6d9e9b3a2c3130207d7e23dfce",
        "87dc1f9846d66e21748adccab0872c1dc4113bc122d58af0446731346b90e34d",
    ),
}


# v0.19.0 has no terminal cause either; the same change, re-ported.
V019_PATCH_PATH = "native/bridge/stream_finish_reason_v019.patch"
V019_SOURCES = {
    "c/conversation.cc": (
        "a7c772314a0a0b6a0efeb9e0835838b6e94d87c54670728ea4c7cd321a3fe4c8",
        "a01a411bdac628d2e90e6bd5a8597a1bc0ba8c6dd0749cd5acb81c82ad547df5",
    ),
    "c/engine_internal.h": (
        "7955c97b6f1c02a8a7828c370d7ec869dc1f1e23b3fa030b1d075e4a6a495af7",
        "e3663bc8be651228f40f6e23cd8ad088bb9975bf85dbc216abf55343157c1ff0",
    ),
    "runtime/conversation/conversation.cc": (
        "ccfbb9afc6af5306e6176435d040e5358c17058bf063b2d5025d1ef0fa4ff591",
        "92e155efa95b5c70bbc78d6f6c099f022056878272166ba41313d7909f924375",
    ),
    "runtime/conversation/conversation.h": (
        "df2af8ccc041b713b8c1a390c2a9cfab3ab1e97bd4697da15bd78d36cea1fbe4",
        "71aaa7ef8227ea675fa39b6a4ddaaed13563e28bebc0c21c36c6ba7355e7486b",
    ),
    "runtime/core/tasks.cc": (
        "c931b91fa7b81b81c8af01cd2f23562ae43f3cce870b177e174c40a95f45ed4f",
        "cbc1d7e16d9dd8d5953a6887d17cde808bf32ed20fcff5c4a69df459720b8915",
    ),
    "runtime/engine/io_types.h": (
        "aefcaf9df9388b6dede3ba222a1a8c8508479e7e894f3a73eebd14a578294f83",
        "c90e7d9a7c307b8f818c351440130e04cb1024d0a77948a5716adac9a053dfdc",
    ),
}


def patch_path_for(compatibility_tag: str) -> str:
    return V019_PATCH_PATH if compatibility_tag == "v0.19.0" else PATCH_PATH


def sources_for(compatibility_tag: str) -> dict[str, tuple[str, str]]:
    return V019_SOURCES if compatibility_tag == "v0.19.0" else SOURCES


def require_finish_reason_patch_decision(compatibility_tag: str) -> bool:
    """Returns whether the patch applies; newer sources need a decision.

    Older runtimes keep reporting no finish reason (bridge ABI version 0).
    """
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) < (0, 18, 0):
        return False
    if compatibility_tag in AUDITED_FINISH_REASON_TAGS:
        return True
    raise RuntimeError(
        f"Stream finish reasons have no explicit decision for "
        f"{compatibility_tag}; revalidate the carried patch or record an "
        "upstream equivalent in tools/stream_finish_reason_patch.py and "
        "docs/upstream_patch_audit.md")


def finish_reason_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_finish_reason_patch_decision(compatibility_tag):
        return []
    patch_path = patch_path_for(compatibility_tag)
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / patch_path).read_bytes()
    ).hexdigest()
    return [{
        "id": "stream-finish-reason",
        "path": patch_path,
        "sha256": patch_sha256,
        "source": source,
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for source, (preimage, postimage) in sources_for(compatibility_tag).items()]
