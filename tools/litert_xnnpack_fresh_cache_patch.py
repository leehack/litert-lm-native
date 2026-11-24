"""Identity of the Linux XNNPACK fresh cache carry."""
import hashlib
from pathlib import Path

from litert_stage_spatial_tensors_patch import LITERT_REF
from source_patch_utils import active_source_carries

PATCH_PATH = "native/bridge/litert_xnnpack_fresh_cache_v020.patch"
SOURCES = {
    "tflite/delegates/xnnpack/weight_cache.cc": (
        "348b1b14d9223a110d0dabea3890fc20bef27fe578c65a8355e02f80a09a630f",
        "5521d7042b36f47539d4c49bcc893ee79d2cd3f1bd8d9c59f2eee2fda08560b6",
    ),
    "tflite/delegates/xnnpack/weight_cache.h": (
        "01d075c069b746eba06797b77906bdb677846c5a0146590dcc22abb07c59a05e",
        "fa6a2da8599a020af5b3796db1b50578d95ac0c480050c5775249413e556537c",
    ),
}


def fresh_cache_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not active_source_carries(compatibility_tag):
        return []
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()
    ).hexdigest()
    return [{
        "id": "litert-xnnpack-fresh-cache",
        "path": PATCH_PATH,
        "sha256": patch_sha256,
        "source": f"LiteRT@{LITERT_REF}/{source}",
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "Linux source-built runtimes with a newly created path-owned XNNPACK cache",
    } for source, (preimage, postimage) in SOURCES.items()]
