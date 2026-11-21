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


def require_stage_spatial_tensors_patch_decision(compatibility_tag: str) -> bool:
    if compatibility_tag == "v0.19.1":
        return True
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) <= (0, 19, 0):
        return False
    raise RuntimeError(
        f"LiteRT spatial tensor staging has no explicit decision for {compatibility_tag}; "
        "requalify the backport or document its retirement in docs/v019_qualification.md"
    )


def verify_litert_pin(workspace: str) -> None:
    # Bazel verifies the archive digest before applying patches, binding the preimages.
    for name, expected in (("LITERT_REF", LITERT_REF),
                           ("LITERT_SHA256", LITERT_ARCHIVE_SHA256)):
        values = re.findall(rf'^{name} = "([0-9a-f]+)"$', workspace, re.MULTILINE)
        if values != [expected]:
            raise RuntimeError(
                f"Unexpected {name} for LiteRT spatial tensor staging; requalify"
            )


def stage_spatial_tensors_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_stage_spatial_tensors_patch_decision(compatibility_tag):
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
