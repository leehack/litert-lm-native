"""Identity of the carried XNNPACK SME2 PQS8/QC4W GEMM opt-out (#84)."""
import hashlib
import re
from pathlib import Path

from xnnpack_pf32_sme2_patch import AUDITED_TAGS, SOURCES as PF32_SOURCES, XNNPACK_COMMIT

PATCH_PATH = "native/bridge/xnnpack_pqs8_qc4w_sme2.patch"
# XNNPACK 76fa737a0 routes int8-activation, int4-weight fully connected layers
# on SME2 CPUs to a packed-LHS path whose only kernel is the 32x32 SME2 MOPA
# one, so single-token decode runs it at M=1 (google/XNNPACK#11793). The patch
# leaves that config empty, keeping those layers on the qs8_qc4w kernels
# v0.18.0 used.
DISABLED_COMMIT = "76fa737a0b70fa506226b23432633e3781c2a470"
# LF-normalized (preimage, postimage) SHA-256 per patched source. The preimage
# is the PF32 rollback's postimage: Bazel applies that patch first.
SOURCES = {
    "src/configs/gemm-config.c": (
        PF32_SOURCES["src/configs/gemm-config.c"][1],
        "fb5075c9e04c562d5c6ed702f18a68117682dd85c3286c9b2e2495c6b44d3f26",
    ),
}


def require_xnnpack_qc4w_patch_decision(compatibility_tag: str) -> bool:
    """Returns whether the opt-out applies; newer sources need a decision."""
    if compatibility_tag in AUDITED_TAGS:
        return True
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) <= (0, 18, 0):
        return False
    raise RuntimeError(
        f"XNNPACK PQS8/QC4W SME2 opt-out has no explicit decision for "
        f"{compatibility_tag}; check the pinned XNNPACK against "
        "google/XNNPACK#11793, then record the decision by adding the tag to "
        "AUDITED_TAGS in tools/xnnpack_pf32_sme2_patch.py (shared with the "
        "PF32 rollback, so audit both) and in docs/upstream_patch_audit.md")


def xnnpack_qc4w_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_xnnpack_qc4w_patch_decision(compatibility_tag):
        return []
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()
    ).hexdigest()
    return [{
        "id": "xnnpack-pqs8-qc4w-sme2",
        "path": PATCH_PATH,
        "sha256": patch_sha256,
        "source": f"XNNPACK@{XNNPACK_COMMIT}/{source}",
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for source, (preimage, postimage) in SOURCES.items()]
