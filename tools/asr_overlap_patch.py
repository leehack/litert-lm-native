"""Identity of the carried untimed merger patch and release patch inventory."""
import hashlib
from pathlib import Path

from android_automatic_gpu_patch import manifest as android_automatic_gpu_manifest
from android_gpu_safety_patch import manifest as android_gpu_safety_manifest
from huggingface_token_bytes_patch import token_bytes_patch_manifest
from litert_stage_spatial_tensors_patch import stage_spatial_tensors_patch_manifest
from litert_xnnpack_fresh_cache_patch import fresh_cache_patch_manifest
from source_patch_utils import active_source_carries
from stream_finish_reason_patch import finish_reason_patch_manifest
from windows_engine_fd_patch import manifest as windows_engine_fd_manifest
from xnnpack_pf32_sme2_patch import xnnpack_pf32_patch_manifest
from xnnpack_pqs8_qc4w_sme2_patch import xnnpack_qc4w_patch_manifest

PATCH_PATH = "native/bridge/asr_untimed_overlap_v019.patch"
MERGER_SOURCE = "omni/speech2text/timestamp_text_merger.cc"
PREIMAGE_SHA256 = "f6091439b29114fdb6cb010480e9b9b3961cd7c868925dc08f458f822ddecd65"
POSTIMAGE_SHA256 = "4a7949344fb79d7c7e7c6fc4261b74031b1244f6bb83f741229483775efdd835"


def source_sha256(data: bytes) -> str:
    # git apply can emit CRLF under core.autocrlf=true on Windows.
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def source_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not active_source_carries(compatibility_tag):
        return []
    overlap = [{
        "id": "asr-untimed-overlap",
        "path": PATCH_PATH,
        "sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest(),
        "source": MERGER_SOURCE,
        "preimageSha256Lf": PREIMAGE_SHA256,
        "postimageSha256Lf": POSTIMAGE_SHA256,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    }]
    return [*overlap,
        *finish_reason_patch_manifest(compatibility_tag),
        *android_gpu_safety_manifest(compatibility_tag),
        *android_automatic_gpu_manifest(compatibility_tag),
        *windows_engine_fd_manifest(compatibility_tag),
        *xnnpack_pf32_patch_manifest(compatibility_tag),
        *xnnpack_qc4w_patch_manifest(compatibility_tag),
        *token_bytes_patch_manifest(compatibility_tag),
        *fresh_cache_patch_manifest(compatibility_tag),
        *stage_spatial_tensors_patch_manifest(compatibility_tag)]
