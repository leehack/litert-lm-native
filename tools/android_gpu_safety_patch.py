"""Audited C API preflight patch for the exact Android Qwen3 safety policy."""
import hashlib
import re
from pathlib import Path

from source_patch_utils import apply_source_patch

PATCH_PATH = "native/bridge/android_gpu_safety_v019.patch"
# v0.19.1 leaves c/engine.cc and c/BUILD byte-identical to v0.19.0.
AUDITED_TAGS = frozenset({"v0.19.0", "v0.19.1", "v0.20.0"})
SOURCES = {'c/engine.cc': ('d2cefd0a04312b5808daddf730a924e8b83e2b1cc6214a5a12e8b454d56557c2',
                 '9ad52a303234df359a5a47256c512823b691c6c0c656b9a388bd544edda320e7'),
 'c/BUILD': ('f72d6fc3e341497cc9cc5b8ba405b81d8aff1e9eed080cc5e4f281832e066748',
             '6a653c953a0389e44c5cddce60911ee9e148ade08b1b5a087b7657adeeb54d7d')}


V020_PATCH_PATH = "native/bridge/android_gpu_safety_v020.patch"
V020_SOURCES = {
    "c/BUILD": (
        "cdd78f10cbc226bd45602f868dc07ae44bb9ed9ca1c9bf1c965fa9d47c6b34fe",
        "78699dba1264eb02210c370d5741bcc8ab949cc368e3a3176be32a8feba41efb",
    ),
    "c/engine.cc": (
        "7db7cd3001f6060efa7f8c1b8e712098067ba99ed0921b0cb7cb543810599ad5",
        "ff7f6fa7bb692c4bf5cc90c8a5c1f1f10aef74a92a33244a971ad02faf9d540e",
    ),
}


def sources_for(tag: str) -> dict[str, tuple[str, str]]:
    return V020_SOURCES if tag == "v0.20.0" else SOURCES


def patch_path_for(tag: str) -> str:
    return V020_PATCH_PATH if tag == "v0.20.0" else PATCH_PATH


def applies(tag: str) -> bool:
    if tag in AUDITED_TAGS:
        return True
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    if match and tuple(map(int, match.groups())) < (0, 19, 0):
        return False
    raise RuntimeError("Android Qwen3 GPU safety has no audited decision for " + tag)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def apply(source_root: Path, tag: str) -> None:
    if not applies(tag):
        return
    observed = {name: digest(source_root / name) for name in sources_for(tag)}
    if all(observed[name] == post for name, (_, post) in sources_for(tag).items()):
        return
    if any(observed[name] != pre for name, (pre, _) in sources_for(tag).items()):
        raise RuntimeError("C API safety source changed; requalify Android GPU preflight")
    patch = Path(__file__).resolve().parents[1] / patch_path_for(tag)
    apply_source_patch(source_root, patch)
    if any(digest(source_root / name) != post for name, (_, post) in sources_for(tag).items()):
        raise RuntimeError("Android GPU preflight postimage mismatch")


def manifest(tag: str) -> list[dict]:
    if not applies(tag):
        return []
    sha = hashlib.sha256((Path(__file__).resolve().parents[1] / patch_path_for(tag)).read_bytes()).hexdigest()
    return [{"id": "android-qwen3-gpu-safety", "path": patch_path_for(tag), "sha256": sha,
             "source": name, "preimageSha256Lf": pre, "postimageSha256Lf": post,
             "scope": "source-built runtimes only; Android C API guard; excludes official upstream prebuilts"}
            for name, (pre, post) in sources_for(tag).items()]
