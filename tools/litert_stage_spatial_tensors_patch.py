"""Identity of the LiteRT background command-buffer binding backport."""
import hashlib
import re
from pathlib import Path

PATCH_PATH = "native/bridge/litert_stage_spatial_tensors.patch"
UPSTREAM_FIX = "aa9e40cd5e2d892b3a5d8579a7ec6faa696e321e"
LITERT_REF = "dcb657e8a537b2dc944e53e14c7eb43bcd9ededa"
LITERT_ARCHIVE_SHA256 = "601bada4d86862a21105ca656f02a22483d2b5733b9932ce997e4b1f59bf8e52"
SOURCES = {
    "ml_drift_delegate/delegate/gpu_backend_vulkan.cc": (
        "94510294e45a568440e87366facbae6294a1087a52bbbcbab05e5f6ceec6d3dd",
        "ee5943a90770691b5e959152c02aaad642d9f6b42ddfbe08b1e3cb79bf8e614a",
    ),
    "ml_drift_delegate/delegate/gpu_backend_vulkan.h": (
        "10482b2f4cc84e5db67f7385499307dcc930ffa24bfba397e42d2299808d9736",
        "0695e45c94da94b87bbb91325b37ff0162c48deaaf5755abeaa51e68f6d1f0ed",
    ),
    "ml_drift_delegate/delegate/gpu_backend_webgpu.cc": (
        "633b5483a3b25660135e5fff01edbebf43854c547726b85583a0fe4906fb7b8e",
        "d2d0fc662b7dfd0b9fa5f95c04ada48f414b08c8f350a9e1169022371d3df968",
    ),
    "ml_drift_delegate/delegate/gpu_backend_webgpu.h": (
        "bf318922fa10a4de702c9ac39212188e90809a0f9de918c29480c5317229c65c",
        "5b756ac60ad2f183eae4981679bf6235befb2e70b82d6ad0807f7831277706b4",
    ),
}

V020_PATCH_PATH = "native/bridge/litert_stage_spatial_tensors_v020.patch"
V020_LITERT_REF = "bf49eb62406d15948261a840c9dcd8e4f13b478c"
V020_LITERT_ARCHIVE_SHA256 = "f5ee44f21843bc6634c02d20d5abb2e4dc0feb83d702b73b5073f10c008231ba"
V020_SOURCES = {
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


def identity_for(compatibility_tag: str) -> tuple[str, str, str, dict[str, tuple[str, str]]]:
    if compatibility_tag == "v0.20.0":
        return V020_PATCH_PATH, V020_LITERT_REF, V020_LITERT_ARCHIVE_SHA256, V020_SOURCES
    return PATCH_PATH, LITERT_REF, LITERT_ARCHIVE_SHA256, SOURCES


def require_stage_spatial_tensors_patch_decision(compatibility_tag: str) -> bool:
    if compatibility_tag in {"v0.19.1", "v0.20.0"}:
        return True
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) <= (0, 19, 0):
        return False
    raise RuntimeError(
        f"LiteRT spatial tensor staging has no explicit decision for {compatibility_tag}; "
        "requalify the backport or document its retirement in docs/v019_qualification.md"
    )


def stage_spatial_tensors_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_stage_spatial_tensors_patch_decision(compatibility_tag):
        return []
    patch_path, litert_ref, _, sources = identity_for(compatibility_tag)
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / patch_path).read_bytes()
    ).hexdigest()
    return [{
        "id": "litert-stage-spatial-tensors",
        "path": patch_path,
        "sha256": patch_sha256,
        "source": f"LiteRT@{litert_ref}/{source}",
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": ("source-built runtimes only; excludes official upstream prebuilts; "
                  f"backports google-ai-edge/LiteRT@{UPSTREAM_FIX}"),
    } for source, (preimage, postimage) in sources.items()]
