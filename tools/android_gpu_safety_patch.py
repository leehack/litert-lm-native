"""Audited C API preflight patch for the exact Android Qwen3 safety policy."""
import hashlib
from pathlib import Path

from source_patch_utils import active_source_carries, apply_source_patch

PATCH_PATH = "native/bridge/android_gpu_safety_v020.patch"
SOURCES = {
    "c/BUILD": (
        "cdd78f10cbc226bd45602f868dc07ae44bb9ed9ca1c9bf1c965fa9d47c6b34fe",
        "78699dba1264eb02210c370d5741bcc8ab949cc368e3a3176be32a8feba41efb",
    ),
    "c/engine.cc": (
        "7db7cd3001f6060efa7f8c1b8e712098067ba99ed0921b0cb7cb543810599ad5",
        "ff7f6fa7bb692c4bf5cc90c8a5c1f1f10aef74a92a33244a971ad02faf9d540e",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def apply(source_root: Path, tag: str) -> None:
    if not active_source_carries(tag):
        return
    observed = {name: digest(source_root / name) for name in SOURCES}
    if all(observed[name] == post for name, (_, post) in SOURCES.items()):
        return
    if any(observed[name] != pre for name, (pre, _) in SOURCES.items()):
        raise RuntimeError("C API safety source changed; requalify Android GPU preflight")
    patch = Path(__file__).resolve().parents[1] / PATCH_PATH
    apply_source_patch(source_root, patch)
    if any(digest(source_root / name) != post for name, (_, post) in SOURCES.items()):
        raise RuntimeError("Android GPU preflight postimage mismatch")


def manifest(tag: str) -> list[dict]:
    if not active_source_carries(tag):
        return []
    sha = hashlib.sha256((Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest()
    return [{"id": "android-qwen3-gpu-safety", "path": PATCH_PATH, "sha256": sha,
             "source": name, "preimageSha256Lf": pre, "postimageSha256Lf": post,
             "scope": "source-built runtimes only; Android C API guard; excludes official upstream prebuilts"}
            for name, (pre, post) in SOURCES.items()]
