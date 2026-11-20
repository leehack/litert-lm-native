"""Version-bound backport of LiteRT-LM e1f86b05 for independent sequences."""
import hashlib
import re
import subprocess
from pathlib import Path

PATCH_PATH = "native/bridge/step_zero_state_v0191.patch"
SOURCE = "runtime/executor/llm_litert_compiled_model_executor.cc"
PREIMAGE = "5e6898eb07178719c554ed49e4bc79d891badea4ad0576d00af54ef1bd8dbb4c"
POSTIMAGE = "55d0e11532e0e4036fadf0ad7fd122b46b0867adafaf49fd648b7144991b7743"
PATCH = Path(__file__).resolve().parents[1] / PATCH_PATH


def applies(tag: str) -> bool:
    if tag == "v0.19.1":
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
    path = source_root / SOURCE
    digest = _digest(path)
    if digest == POSTIMAGE:
        return
    if digest != PREIMAGE:
        raise RuntimeError("Executor source changed; requalify the step-zero state patch")
    args = ["--ignore-space-change", str(PATCH)]
    subprocess.run(["git", "apply", "--check", *args], check=True, cwd=source_root)
    subprocess.run(["git", "apply", *args], check=True, cwd=source_root)
    if _digest(path) != POSTIMAGE:
        raise RuntimeError("Executor step-zero state postimage mismatch")


def manifest(tag: str) -> list[dict]:
    if not applies(tag):
        return []
    return [{
        "id": "step-zero-state",
        "path": PATCH_PATH,
        "sha256": hashlib.sha256(PATCH.read_bytes()).hexdigest(),
        "source": SOURCE,
        "preimageSha256Lf": PREIMAGE,
        "postimageSha256Lf": POSTIMAGE,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    }]
