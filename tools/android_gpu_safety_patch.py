"""Audited C API preflight patch for the exact Android Qwen3 safety policy."""
import hashlib
from pathlib import Path
import re
import subprocess

PATCH_PATH = "native/bridge/android_gpu_safety_v019.patch"
SOURCES = {'c/engine.cc': ('d2cefd0a04312b5808daddf730a924e8b83e2b1cc6214a5a12e8b454d56557c2',
                 '9ad52a303234df359a5a47256c512823b691c6c0c656b9a388bd544edda320e7'),
 'c/BUILD': ('f72d6fc3e341497cc9cc5b8ba405b81d8aff1e9eed080cc5e4f281832e066748',
             '6a653c953a0389e44c5cddce60911ee9e148ade08b1b5a087b7657adeeb54d7d')}


def applies(tag: str) -> bool:
    if tag == "v0.19.0":
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
    observed = {name: digest(source_root / name) for name in SOURCES}
    if all(observed[name] == post for name, (_, post) in SOURCES.items()):
        return
    if any(observed[name] != pre for name, (pre, _) in SOURCES.items()):
        raise RuntimeError("C API safety source changed; requalify Android GPU preflight")
    patch = Path(__file__).resolve().parents[1] / PATCH_PATH
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=source_root, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=source_root, check=True)
    if any(digest(source_root / name) != post for name, (_, post) in SOURCES.items()):
        raise RuntimeError("Android GPU preflight postimage mismatch")


def manifest(tag: str) -> list[dict]:
    if not applies(tag):
        return []
    sha = hashlib.sha256((Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest()
    return [{"id": "android-qwen3-gpu-safety", "path": PATCH_PATH, "sha256": sha,
             "source": name, "preimageSha256Lf": pre, "postimageSha256Lf": post,
             "scope": "source-built runtimes only; Android C API guard; excludes official upstream prebuilts"}
            for name, (pre, post) in SOURCES.items()]
