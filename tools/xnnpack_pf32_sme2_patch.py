"""Identity of the carried XNNPACK PF32 SME2 GEMM opt-out (#82)."""
import hashlib
import re
from pathlib import Path

PATCH_PATH = "native/bridge/xnnpack_pf32_sme2.patch"
AUDITED_TAGS = frozenset({"v0.18.1"})
# v0.18.1 pins TensorFlow a1179d3c, whose XLA pins this XNNPACK. It contains
# 70a9c5e8ac (KleidiAI PF32 SME2 GEMM), which is nondeterministic with more
# than one thread (google/XNNPACK#11789). v0.18.0 pins an XNNPACK without it.
TENSORFLOW_REF = "a1179d3c224967bd979950b823d5ce2a7e8f4c94"
XNNPACK_COMMIT = "d89ef6669a14db203b3b7935b1b3862cb63fb6df"
XNNPACK_SHA256 = "aab0ed2b3972125ca057b8e2b16127fbf68f8128ea07dd7efe56cdb92f2c1917"
XNNPACK_URL = f"https://github.com/google/XNNPACK/archive/{XNNPACK_COMMIT}.zip"
SOURCE = "src/configs/gemm-config.c"
# LF-normalized (preimage, postimage) SHA-256 of SOURCE in XNNPACK_COMMIT.
SOURCE_SHA256 = (
    "0967ea0d1d9aba4c0efc2bf64f2c4683201e2e34f6d7f8b1bb74aa3b93fd7fb1",
    "eefbc42e0a7fe8de12ea179ff8d61ee7ff568b22ea4f5ffdcc805de0b91b7148",
)
# Declared ahead of tf_workspace2(): XLA's tf_http_archive skips a repository
# that already exists, so this exact archive is the one every target links.
ARCHIVE = f'''# XNNPACK pinned by TensorFlow {TENSORFLOW_REF[:8]} (XLA third_party/xnnpack),
# with the PF32 SME2 GEMM disabled (litert-lm-native#82).
http_archive(
    name = "XNNPACK",
    patch_args = ["-p1"],
    patches = ["@//bridge:xnnpack_pf32_sme2.patch"],
    sha256 = "{XNNPACK_SHA256}",
    strip_prefix = "XNNPACK-{XNNPACK_COMMIT}",
    urls = [
        "https://storage.googleapis.com/mirror.tensorflow.org/{XNNPACK_URL[8:]}",
        "{XNNPACK_URL}",
    ],
)

'''


def require_xnnpack_pf32_patch_decision(compatibility_tag: str) -> bool:
    """Returns whether the opt-out applies; newer sources need a decision."""
    if compatibility_tag in AUDITED_TAGS:
        return True
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) <= (0, 18, 0):
        return False
    raise RuntimeError(
        f"XNNPACK PF32 SME2 opt-out has no explicit decision for "
        f"{compatibility_tag}; check the pinned XNNPACK against "
        "google/XNNPACK#11789 and record the decision in "
        "tools/xnnpack_pf32_sme2_patch.py and docs/upstream_patch_audit.md")


def declare_patched_xnnpack(workspace_text: str) -> str:
    """Inserts the patched XNNPACK archive before the TensorFlow archive."""
    if ARCHIVE in workspace_text:
        return workspace_text
    refs = re.findall(r'^TENSORFLOW_REF = "([0-9a-f]{40})"$', workspace_text, re.MULTILINE)
    # Starlark uses the last assignment.
    if not refs or refs[-1] != TENSORFLOW_REF:
        raise RuntimeError("TensorFlow pin changed; requalify the XNNPACK PF32 SME2 opt-out")
    if re.search(r'^\s*name = "XNNPACK",$', workspace_text, re.MULTILINE):
        raise RuntimeError("Unexpected XNNPACK archive in WORKSPACE; requalify the PF32 SME2 opt-out")
    anchor = '# TensorFlow\nhttp_archive(\n    name = "org_tensorflow",\n'
    if workspace_text.count(anchor) != 1:
        raise RuntimeError("Expected one TensorFlow archive in WORKSPACE")
    return workspace_text.replace(anchor, ARCHIVE + anchor, 1)


def xnnpack_pf32_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not require_xnnpack_pf32_patch_decision(compatibility_tag):
        return []
    patch_sha256 = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()
    ).hexdigest()
    return [{
        "id": "xnnpack-pf32-sme2",
        "path": PATCH_PATH,
        "sha256": patch_sha256,
        "source": f"XNNPACK@{XNNPACK_COMMIT}/{SOURCE}",
        "preimageSha256Lf": SOURCE_SHA256[0],
        "postimageSha256Lf": SOURCE_SHA256[1],
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    }]
