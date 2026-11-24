"""Keep Android GPU backend selection automatic in the source-built runtime."""

import hashlib
import json
from pathlib import Path

from source_patch_utils import active_source_carries, apply_source_patch

PATCH_PATH = "native/bridge/android_automatic_gpu_v020.patch"
SOURCES = {
    "runtime/executor/BUILD": (
        "62480789d83f9d1e963dfb07653e4fb8881bb44141f31453d11ad602be0272c7",
        "062badcf243706b668fa32f6043ad374ec89fa550fc2f3fa331308666d01a0c5",
    ),
    "runtime/components/BUILD": (
        "a5979921e502c391286e434fa5d567754a9b612bc3257d38ea056b43c999a432",
        "e9bb1da7b1d919319b917914495989420864c4583f2a71cb0d2779459871cb8e",
    ),
}
EXECUTOR_PREFIX = "//runtime/executor:"
EXECUTORS = (
    "audio_litert_compiled_model_executor",
    "litert_compiled_model_executor_utils",
    "llm_executor_settings_utils",
    "vision_litert_compiled_model_executor",
)
FORCED_BACKEND = "LITERT_USE_WEBGPU_ACCELERATOR"


def _digest(source: Path) -> str:
    return hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def apply(source_root: Path, tag: str) -> None:
    if not active_source_carries(tag):
        return
    observed = {name: _digest(source_root / name) for name in SOURCES}
    if all(observed[name] == after for name, (_, after) in SOURCES.items()):
        return
    if any(observed[name] != before for name, (before, _) in SOURCES.items()):
        raise RuntimeError("Android GPU BUILD sources changed; requalify automatic backend patch")
    apply_source_patch(source_root, Path(__file__).resolve().parents[1] / PATCH_PATH)
    if any(_digest(source_root / name) != after for name, (_, after) in SOURCES.items()):
        raise RuntimeError("Android GPU BUILD postimage mismatch; requalify automatic backend patch")


def manifest(tag: str) -> list[dict]:
    if not active_source_carries(tag):
        return []
    digest = hashlib.sha256((Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest()
    return [{
        "id": "android-automatic-gpu",
        "path": PATCH_PATH,
        "sha256": digest,
        "source": name,
        "preimageSha256Lf": before,
        "postimageSha256Lf": after,
        "scope": "Android source-built runtimes only; combined accelerator and both static samplers",
    } for name, (before, after) in SOURCES.items()]


def executor_compile_query(runtime_target: str) -> str:
    labels = "|".join(EXECUTORS)
    return f'mnemonic("CppCompile", filter("^{EXECUTOR_PREFIX}({labels})$", deps({runtime_target})))'


def verify_executor_compile_actions(output: str) -> None:
    graph = json.loads(output)
    targets = {target["id"]: target["label"] for target in graph.get("targets", [])}
    checked = set()
    for action in graph.get("actions", []):
        label = targets[action["targetId"]]
        arguments = action["arguments"] + [
            arg for params in action.get("paramFiles", []) for arg in params["arguments"]
        ]
        if any(arg.split("=", 1)[0] in {FORCED_BACKEND, f"-D{FORCED_BACKEND}"} for arg in arguments):
            raise RuntimeError(f"Android GPU backend is forced to WebGPU in {label}")
        checked.add(label)
    missing = {EXECUTOR_PREFIX + executor for executor in EXECUTORS} - checked
    if missing:
        raise RuntimeError(f"Android GPU compile actions missing for {', '.join(sorted(missing))}")
    print("Verified Android GPU backend is automatic in: " + ", ".join(sorted(checked)), flush=True)
