"""Version-bound step-zero reset and macOS linear-attention sampler policy."""
import hashlib
import re
from pathlib import Path

from source_patch_utils import apply_source_patch

PATCH_PATH = "native/bridge/step_zero_state_v0191.patch"
SOURCE = "runtime/executor/llm_litert_compiled_model_executor.cc"
PREIMAGE = "5e6898eb07178719c554ed49e4bc79d891badea4ad0576d00af54ef1bd8dbb4c"
POSTIMAGE = "b2c73fbcb400654072bf926dbaa3b81e252acf750f8fc1a60dd0b51df84d890d"

V020_PATCH_PATH = "native/bridge/step_zero_state_v020.patch"
V020_PREIMAGE = "4ccb5ef331ab7d10927d618fee8041cf030500700646efeb2aab0e57c3212c32"
V020_POSTIMAGE = "96ebbe1e0cdbdcfe00407cf6ead2b2df1073ab9eb53695a917bf487da3482e7a"


def identity_for(tag: str) -> tuple[str, str, str]:
    if tag == "v0.20.0":
        return V020_PATCH_PATH, V020_PREIMAGE, V020_POSTIMAGE
    return PATCH_PATH, PREIMAGE, POSTIMAGE


def applies(tag: str) -> bool:
    if tag in {"v0.19.1", "v0.20.0"}:
        return True
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    if version and tuple(map(int, version.groups())) < (0, 19, 1):
        return False
    raise RuntimeError(f"Step-zero state has no explicit decision for {tag}; "
                       "requalify the carry in docs/v019_qualification.md")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def apply(source_root: Path, tag: str) -> None:
    if not applies(tag):
        return
    patch_path, preimage, postimage = identity_for(tag)
    path = source_root / SOURCE
    digest = _digest(path)
    if digest == postimage:
        return
    if digest != preimage:
        raise RuntimeError("Executor source changed; requalify the step-zero state patch")
    patch = Path(__file__).resolve().parents[1] / patch_path
    apply_source_patch(source_root, patch, ignore_space_change=True)
    if _digest(path) != postimage:
        raise RuntimeError("Executor step-zero state postimage mismatch")


def manifest(tag: str) -> list[dict]:
    if not applies(tag):
        return []
    patch_path, preimage, postimage = identity_for(tag)
    patch = Path(__file__).resolve().parents[1] / patch_path
    return [{
        "id": "step-zero-state",
        "path": patch_path,
        "sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "source": SOURCE,
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    }]
