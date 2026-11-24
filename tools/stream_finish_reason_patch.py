"""Identity of the carried stream finish-reason patch (#78)."""
import hashlib
from pathlib import Path

from source_patch_utils import active_source_carries

BAZEL_DEFINE = "--define=litert_lm_finish_reason_api=true"
PATCH_PATH = "native/bridge/stream_finish_reason_v020.patch"
SOURCES = {
    "c/c_api_internal.h": (
        "bcd6bce2a4b986f2cac4ba8869fef944cd3ee2fa47f21f837a1ff5c5876c1504",
        "546a4e509e368d2d0a3232df4f9c204d9c66beb9fe17fdca089e1ce5a545a777",
    ),
    "c/conversation.cc": (
        "518fe5457b36a020fe49b8370390ee47725afd083f457a7b92877fc55e98c246",
        "ef6ea2b8ec99fdc04704e93dff71ae1d125b2c3269268fd502eb87f6f7fb06e1",
    ),
    "c/engine_internal.h": (
        "7955c97b6f1c02a8a7828c370d7ec869dc1f1e23b3fa030b1d075e4a6a495af7",
        "e3663bc8be651228f40f6e23cd8ad088bb9975bf85dbc216abf55343157c1ff0",
    ),
    "runtime/conversation/conversation.cc": (
        "2c91850bcc70d953d45ff52084dd29a110a74bb5a83b142d73807c147b87579e",
        "bcd284bc4738df7c2e360e1f14ca734962a4688ee2ea79ba493ef820b68ec15e",
    ),
    "runtime/conversation/conversation.h": (
        "3d3b936089c13142e65a195fee59ba2449734f5a338074eb9f9e5ccb419639cf",
        "3c4280fe15bbebc003dd9b97bb4a78f9db52cd952afa34279f9826282a7383b3",
    ),
    "runtime/core/tasks.cc": (
        "3970f6f747fc39e05746c3e80d4cadc315be28b01cf4911ed05aee7f40df10df",
        "38e068714f2995b86fb57121f2261369c471e1d5040a812f2531bacd96cb080a",
    ),
    "runtime/engine/io_types.h": (
        "99da02ec968a379099ca86e25ba5a0f91df820de1b58d9315c4c1215ac9474b3",
        "2c7c79d5a0f8d6de47fb8c3220de3b8b37230f9c49f8f4772f93dfa3b79f2a89",
    ),
}


def finish_reason_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not active_source_carries(compatibility_tag):
        return []
    patch_path = PATCH_PATH
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
    } for source, (preimage, postimage) in SOURCES.items()]
