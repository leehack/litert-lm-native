"""Identity of the LiteRT background command-buffer binding backport."""
import hashlib
from pathlib import Path

from source_patch_utils import active_source_carries

UPSTREAM_FIX = "aa9e40cd5e2d892b3a5d8579a7ec6faa696e321e"
PATCH_PATH = "native/bridge/litert_stage_spatial_tensors_v020.patch"
LITERT_REF = "bf49eb62406d15948261a840c9dcd8e4f13b478c"
LITERT_ARCHIVE_SHA256 = "f5ee44f21843bc6634c02d20d5abb2e4dc0feb83d702b73b5073f10c008231ba"
SOURCES = {
    "ml_drift_delegate/delegate/gpu_backend_vulkan.cc": (
        "94510294e45a568440e87366facbae6294a1087a52bbbcbab05e5f6ceec6d3dd",
        "ee5943a90770691b5e959152c02aaad642d9f6b42ddfbe08b1e3cb79bf8e614a",
    ),
    "ml_drift_delegate/delegate/gpu_backend_vulkan.h": (
        "5d7b59f6e1c03749333bd650911c1ffc0e911932d65b0762c87f5616574ceb0b",
        "66eebf4c18828637fcbcdb360c2192a446c070e5519fd61936b782f2faa5363b",
    ),
    "ml_drift_delegate/delegate/gpu_backend_webgpu.cc": (
        "38906e7dd17317e946eff46e8b185505bf1f463043d19b24318b30d4e4089bb5",
        "1d8ab8c31766429ee5e4423a62aa60dab6b09abcfb81f7672474d22b49978dad",
    ),
    "ml_drift_delegate/delegate/gpu_backend_webgpu.h": (
        "e6b0a47805e83db622ce65d6d8bb5535a03a867456e4bcb72ae16044ce23f041",
        "9c795eedf6256288b1e7f33bff028d5af99e9958d6568dd40276d4bda46b06c3",
    ),
}


def stage_spatial_tensors_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not active_source_carries(compatibility_tag):
        return []
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()
    ).hexdigest()
    return [{
        "id": "litert-stage-spatial-tensors",
        "path": PATCH_PATH,
        "sha256": patch_sha256,
        "source": f"LiteRT@{LITERT_REF}/{source}",
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": ("source-built runtimes only; excludes official upstream prebuilts; "
                  f"backports google-ai-edge/LiteRT@{UPSTREAM_FIX}"),
    } for source, (preimage, postimage) in SOURCES.items()]
