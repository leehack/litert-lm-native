"""Identity of the carried LiteRT CPU options identifier rollback (#89)."""
import hashlib
import re
from pathlib import Path

PATCH_PATH = "native/bridge/litert_cpu_options_identifier.patch"
AUDITED_TAGS = frozenset({"v0.18.1"})
# v0.19.0 ships Linux and Windows prebuilt libLiteRt that read "cpu_options",
# the same identifier its pinned LiteRT dcb657e8 writes.
UPSTREAM_FIX_TAGS = frozenset({"v0.19.0"})
# LiteRT 724a247cc5 renamed the CPU options identifier from "xnnpack" to
# "cpu_options". v0.18.1 pins LiteRT ca21dc99, which has the rename, but still
# ships the 2026-09-28 prebuilt libLiteRt from before it. Linux and Windows
# hosts link that runtime, whose XNNPACK accelerator looks up only "xnnpack",
# so it dropped every CPU option, including the thread count. Static runtimes
# read the identifier from the same function, so the patch is neutral there.
RENAME_COMMIT = "724a247cc5"
LITERT_REF = "ca21dc99de51c76bdcc572afeea1dd937d3c9e5c"
SOURCE = "litert/c/options/litert_cpu_options.cc"
# LF-normalized (preimage, postimage) SHA-256 of SOURCE.
SOURCES = {
    SOURCE: (
        "ecfa9e2523dfae8c1417c12e4bb02c1b7b3c6bcaa6f93310ff4c859978485b09",
        "bb7008295ad9e0a3ccc6a2a0119c14e7cafa481792512dc4bed2b06890347cb9",
    ),
}
# Upstream v0.18.1 prebuilt runtimes audited to read "xnnpack".
DYNAMIC_RUNTIMES = {
    ("linux", "arm64"): (
        "linux_arm64/libLiteRt.so",
        "989bccd9c950ad8ae8fa40a3febb54490cc7960ad81d260b36c9480574e8092a",
    ),
    ("linux", "x64"): (
        "linux_x86_64/libLiteRt.so",
        "88beda3e49caf68332d4b2ff418f7f42f34830e4ec54587f3b3e381d4462ab2d",
    ),
    ("windows", "x64"): (
        "windows_x86_64/libLiteRt.dll",
        "d027bceb59db9402abe3b20f61e3e6eab329b4f7c5665e7228b64871e7164c8a",
    ),
}


def require_cpu_options_identifier_patch_decision(compatibility_tag: str) -> bool:
    """Returns whether the rollback applies; newer sources need a decision."""
    if compatibility_tag in AUDITED_TAGS:
        return True
    if compatibility_tag in UPSTREAM_FIX_TAGS:
        return False
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) <= (0, 18, 0):
        return False
    raise RuntimeError(
        f"LiteRT CPU options identifier rollback has no explicit decision for "
        f"{compatibility_tag}; check which identifier the pinned LiteRT and the "
        "Linux/Windows prebuilt libLiteRt use, then record the decision in "
        "tools/litert_cpu_options_identifier_patch.py and "
        "docs/upstream_patch_audit.md")


def verify_dynamic_runtime(prebuilt_root: Path, platform: str, arch: str) -> None:
    """Fails unless a dynamic host links the prebuilt runtime this patch targets."""
    if (platform, arch) not in DYNAMIC_RUNTIMES:
        return
    name, digest = DYNAMIC_RUNTIMES[(platform, arch)]
    runtime = prebuilt_root / name
    if not runtime.is_file() or hashlib.sha256(runtime.read_bytes()).hexdigest() != digest:
        raise RuntimeError(
            f"Prebuilt {name} changed; requalify the CPU options identifier rollback")


def cpu_options_identifier_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_cpu_options_identifier_patch_decision(compatibility_tag):
        return []
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()
    ).hexdigest()
    return [{
        "id": "litert-cpu-options-identifier",
        "path": PATCH_PATH,
        "sha256": patch_sha256,
        "source": f"LiteRT@{LITERT_REF}/{source}",
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for source, (preimage, postimage) in SOURCES.items()]
