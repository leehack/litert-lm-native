"""Identity of the carried v0.18 untimed merger source transformation."""
import hashlib
from pathlib import Path

PREIMAGE_SHA256 = "6458bdfb32cbb32250c5be8843d303a9759da96f5675eae2d23a5f01f41dc826"
POSTIMAGE_SHA256 = "c320a49202fcaed40ef2619e977b3a44303e7aa9aa04012c94a6ca07c016caee"
PATCH_PATH = "native/bridge/asr_untimed_overlap.patch"


def source_sha256(data: bytes) -> str:
    # git apply can emit CRLF under core.autocrlf=true on Windows.
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def source_patch_manifest(compatibility_tag: str) -> list[dict]:
    if compatibility_tag != "v0.18.0":
        return []
    return [{
        "id": "asr-untimed-overlap",
        "path": PATCH_PATH,
        "sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest(),
        "source": "omni/asr/timestamp_text_merger.cc",
        "preimageSha256Lf": PREIMAGE_SHA256,
        "postimageSha256Lf": POSTIMAGE_SHA256,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    }]
