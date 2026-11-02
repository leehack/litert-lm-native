"""Identity of the carried v0.18 untimed merger source transformation."""
import hashlib
import re
from pathlib import Path

from asr_litertlm_container_patch import container_patch_manifest
from litert_cpu_options_identifier_patch import cpu_options_identifier_patch_manifest
from stream_finish_reason_patch import finish_reason_patch_manifest
from workspace_build_patch import workspace_build_patch_manifest
from xnnpack_pf32_sme2_patch import xnnpack_pf32_patch_manifest
from xnnpack_pqs8_qc4w_sme2_patch import xnnpack_qc4w_patch_manifest

PREIMAGE_SHA256 = "6458bdfb32cbb32250c5be8843d303a9759da96f5675eae2d23a5f01f41dc826"
AUDITED_OVERLAP_TAGS = frozenset({"v0.18.0", "v0.18.1"})
POSTIMAGE_SHA256 = "c320a49202fcaed40ef2619e977b3a44303e7aa9aa04012c94a6ca07c016caee"
PATCH_PATH = "native/bridge/asr_untimed_overlap.patch"
MERGER_SOURCE = "omni/asr/timestamp_text_merger.cc"
# v0.19.0 moved and rewrote the merger; its seam-run fallback still mis-seams
# repeated phrases at the bridge's 0.4 overlap (docs/asr_untimed_overlap.md).
V019_PREIMAGE_SHA256 = "1ddbc15f935d63ca123011e7e4864b33b78b8cd5ee292b9d3bccf90d2bdb378f"
V019_POSTIMAGE_SHA256 = "3b135f027b369ceadb734117d416071e4e64837304f49b90e77e8f9d19fec060"
V019_PATCH_PATH = "native/bridge/asr_untimed_overlap_v019.patch"
V019_MERGER_SOURCE = "omni/speech2text/timestamp_text_merger.cc"
V019_OVERLAP_TAGS = frozenset({"v0.19.0"})


def merger_source(compatibility_tag: str) -> str:
    return (V019_MERGER_SOURCE if compatibility_tag in V019_OVERLAP_TAGS
            else MERGER_SOURCE)


def overlap_identity(compatibility_tag: str) -> tuple[str, str, str]:
    """Returns the patch path, preimage and postimage for an audited tag."""
    if compatibility_tag in V019_OVERLAP_TAGS:
        return V019_PATCH_PATH, V019_PREIMAGE_SHA256, V019_POSTIMAGE_SHA256
    return PATCH_PATH, PREIMAGE_SHA256, POSTIMAGE_SHA256


def source_sha256(data: bytes) -> str:
    # git apply can emit CRLF under core.autocrlf=true on Windows.
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def require_asr_patch_decision(compatibility_tag: str) -> None:
    """Older releases predate this carry; newer/unknown sources need a decision.

    Deliberately no environment/CLI bypass: extending support means checking in
    a revalidated patch or a documented, version-specific retirement decision.
    """
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) < (0, 18, 0):
        return
    if compatibility_tag in AUDITED_OVERLAP_TAGS | V019_OVERLAP_TAGS:
        return
    raise RuntimeError(
        f"ASR untimed overlap has no explicit decision for {compatibility_tag}; "
        "revalidate the carried patch or record a version-specific opt-out with "
        "evidence in tools/asr_overlap_patch.py and docs/asr_untimed_overlap.md "
        "before building or releasing this version")


def source_patch_manifest(compatibility_tag: str) -> list[dict]:
    require_asr_patch_decision(compatibility_tag)
    carried = compatibility_tag in AUDITED_OVERLAP_TAGS | V019_OVERLAP_TAGS
    patch_path, preimage, postimage = overlap_identity(compatibility_tag)
    overlap = [] if not carried else [{
        "id": "asr-untimed-overlap",
        "path": patch_path,
        "sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / patch_path).read_bytes()).hexdigest(),
        "source": merger_source(compatibility_tag),
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    }]
    return [*overlap, *container_patch_manifest(compatibility_tag),
        *finish_reason_patch_manifest(compatibility_tag),
        *workspace_build_patch_manifest(compatibility_tag),
        *xnnpack_pf32_patch_manifest(compatibility_tag),
        *xnnpack_qc4w_patch_manifest(compatibility_tag),
        *cpu_options_identifier_patch_manifest(compatibility_tag)]
