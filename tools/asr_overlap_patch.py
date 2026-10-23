"""Identity of the carried v0.18 untimed merger source transformation."""
import hashlib
import re
from pathlib import Path

from asr_litertlm_container_patch import container_patch_manifest
from stream_finish_reason_patch import finish_reason_patch_manifest
from workspace_build_patch import workspace_build_patch_manifest
from xnnpack_pf32_sme2_patch import xnnpack_pf32_patch_manifest

PREIMAGE_SHA256 = "6458bdfb32cbb32250c5be8843d303a9759da96f5675eae2d23a5f01f41dc826"
AUDITED_OVERLAP_TAGS = frozenset({"v0.18.0", "v0.18.1"})
POSTIMAGE_SHA256 = "c320a49202fcaed40ef2619e977b3a44303e7aa9aa04012c94a6ca07c016caee"
PATCH_PATH = "native/bridge/asr_untimed_overlap.patch"


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
    if compatibility_tag in AUDITED_OVERLAP_TAGS:
        return
    raise RuntimeError(
        f"ASR untimed overlap has no explicit decision for {compatibility_tag}; "
        "revalidate the carried patch or record a version-specific opt-out with "
        "evidence in tools/asr_overlap_patch.py and docs/asr_untimed_overlap.md "
        "before building or releasing this version")


def source_patch_manifest(compatibility_tag: str) -> list[dict]:
    require_asr_patch_decision(compatibility_tag)
    if compatibility_tag not in AUDITED_OVERLAP_TAGS:
        return container_patch_manifest(compatibility_tag)
    return [{
        "id": "asr-untimed-overlap",
        "path": PATCH_PATH,
        "sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest(),
        "source": "omni/asr/timestamp_text_merger.cc",
        "preimageSha256Lf": PREIMAGE_SHA256,
        "postimageSha256Lf": POSTIMAGE_SHA256,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    }, *container_patch_manifest(compatibility_tag),
        *finish_reason_patch_manifest(compatibility_tag),
        *workspace_build_patch_manifest(compatibility_tag),
        *xnnpack_pf32_patch_manifest(compatibility_tag)]
