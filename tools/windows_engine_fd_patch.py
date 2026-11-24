"""Pin the MSVC-compatible engine-settings file descriptor source."""

import hashlib
import re
from pathlib import Path

from android_gpu_safety_patch import V020_SOURCES, apply as apply_android_gpu_safety, digest
from source_patch_utils import apply_source_patch

PATCH_PATH = "native/bridge/windows_engine_fd_v020.patch"
SOURCE = "c/engine.cc"
PREIMAGE_SHA256 = V020_SOURCES[SOURCE][1]
POSTIMAGE_SHA256 = "c6371431aa7d7d95a2ec0ec1a317be83efd5ae4513f14dd46c51fb0c15816b30"


def require_windows_engine_fd_patch_decision(tag: str) -> bool:
    if tag == "v0.20.0":
        return True
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    if version and tuple(map(int, version.groups())) < (0, 20, 0):
        return False
    raise RuntimeError(f"Windows engine file descriptor patch has no explicit decision for {tag}")


def apply(source_root: Path, tag: str) -> None:
    if not require_windows_engine_fd_patch_decision(tag):
        return
    source = source_root / SOURCE
    # Both patches touch engine.cc. A retry must also verify the GPU guard's BUILD edit.
    if digest(source) == POSTIMAGE_SHA256:
        if digest(source_root / "c/BUILD") != V020_SOURCES["c/BUILD"][1]:
            raise RuntimeError("C API BUILD source changed; requalify Android GPU preflight")
        return
    apply_android_gpu_safety(source_root, tag)
    if digest(source) != PREIMAGE_SHA256:
        raise RuntimeError("Windows engine file descriptor preimage mismatch; requalify")
    patch_file = Path(__file__).resolve().parents[1] / PATCH_PATH
    apply_source_patch(source_root, patch_file, ignore_space_change=True)
    if digest(source) != POSTIMAGE_SHA256:
        raise RuntimeError("Windows engine file descriptor postimage mismatch; requalify")


def manifest(tag: str) -> list[dict]:
    if not require_windows_engine_fd_patch_decision(tag):
        return []
    patch_file = Path(__file__).resolve().parents[1] / PATCH_PATH
    return [{
        "id": "windows-engine-fd",
        "path": PATCH_PATH,
        "sha256": hashlib.sha256(patch_file.read_bytes()).hexdigest(),
        "source": SOURCE,
        "preimageSha256Lf": PREIMAGE_SHA256,
        "postimageSha256Lf": POSTIMAGE_SHA256,
        "scope": "Windows source-built runtimes only; applies after Android GPU preflight",
    }]
