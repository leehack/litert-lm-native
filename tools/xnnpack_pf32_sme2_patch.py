"""Identity of the carried XNNPACK PF32 SME2 kernel rollback (#82)."""
import hashlib
import re
from pathlib import Path

PATCH_PATH = "native/bridge/xnnpack_pf32_sme2.patch"
AUDITED_TAGS = frozenset({"v0.18.1"})
# v0.18.1 pins TensorFlow a1179d3c, whose XLA pins this XNNPACK. It contains
# 70a9c5e8ac, which moved the PF32 SME2 GEMM/GEMV to KleidiAI kernels that are
# nondeterministic with more than one thread (google/XNNPACK#11789). The patch
# reverts that commit's SME2 kernel, LHS-packing and RHS-packing selection;
# v0.18.0 pins an XNNPACK from before it.
REVERTED_COMMIT = "70a9c5e8acf90bef0c56f33a14529027585fd436"
TENSORFLOW_REF = "a1179d3c224967bd979950b823d5ce2a7e8f4c94"
XNNPACK_COMMIT = "d89ef6669a14db203b3b7935b1b3862cb63fb6df"
XNNPACK_SHA256 = "aab0ed2b3972125ca057b8e2b16127fbf68f8128ea07dd7efe56cdb92f2c1917"
XNNPACK_URL = f"https://github.com/google/XNNPACK/archive/{XNNPACK_COMMIT}.zip"
# LF-normalized (preimage, postimage) SHA-256 per patched XNNPACK_COMMIT source.
SOURCES = {
    "src/configs/gemm-config.c": (
        "0967ea0d1d9aba4c0efc2bf64f2c4683201e2e34f6d7f8b1bb74aa3b93fd7fb1",
        "7297696007430648a2bf3b1bbde03d9f32b7cbcbcf8a84ba79bfddd9887909e3",
    ),
    "src/pf32-gemm/pf32-gemm-1x32-minmax-neonsme2.c": (
        "777115eb004977880b26ec4313d94a09f73157cbc44f3196585a1497411cbcc7",
        "5d9972ed94ad8382fa184ffd66709cccaf932aa2a20b91b419834ca45c04f7b8",
    ),
    "src/pf32-gemm/pf32-gemm-32x32-minmax-neonsme2.c": (
        "f101b386705e62f257c8c7e613474dd811d968316e968e2ff415fefe064f3abe",
        "aa692a7cfbfa6c88df6185caba1938502842d92219c9fe3e728cf1a08aa95301",
    ),
    "src/x32-pack-lh/x32-packlh-neonsme2.c": (
        "820b6c397d740e63efb03ab23be9a0c337b147a302dbce139ddcf55b7b8216f8",
        "5aa0176053653592a86ebc848261029f2494e23f9c9be25cc9923afc901345c0",
    ),
}
# Declared ahead of tf_workspace2(): XLA's tf_http_archive skips a repository
# that already exists, so this exact archive is the one every target links.
# Patches apply in order; the PQS8/QC4W opt-out (#84) edits the PF32 postimage
# of src/configs/gemm-config.c.
ARCHIVE = f'''# XNNPACK pinned by TensorFlow {TENSORFLOW_REF[:8]} (XLA third_party/xnnpack),
# with the PF32 SME2 kernels of {REVERTED_COMMIT[:10]} reverted (litert-lm-native#82)
# and the SME2 PQS8/QC4W GEMM config disabled (litert-lm-native#84).
http_archive(
    name = "XNNPACK",
    patch_args = ["-p1"],
    patches = [
        "@//bridge:xnnpack_pf32_sme2.patch",
        "@//bridge:xnnpack_pqs8_qc4w_sme2.patch",
    ],
    sha256 = "{XNNPACK_SHA256}",
    strip_prefix = "XNNPACK-{XNNPACK_COMMIT}",
    urls = [
        "https://storage.googleapis.com/mirror.tensorflow.org/{XNNPACK_URL[8:]}",
        "{XNNPACK_URL}",
    ],
)

'''


def require_xnnpack_pf32_patch_decision(compatibility_tag: str) -> bool:
    """Returns whether the rollback applies; newer sources need a decision."""
    if compatibility_tag in AUDITED_TAGS:
        return True
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", compatibility_tag)
    if version and tuple(map(int, version.groups())) <= (0, 18, 0):
        return False
    raise RuntimeError(
        f"XNNPACK PF32 SME2 rollback has no explicit decision for "
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
        raise RuntimeError("TensorFlow pin changed; requalify the XNNPACK patches")
    if re.search(r'^\s*name = "XNNPACK",$', workspace_text, re.MULTILINE):
        raise RuntimeError("Unexpected XNNPACK archive in WORKSPACE; requalify the XNNPACK patches")
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
        "source": f"XNNPACK@{XNNPACK_COMMIT}/{source}",
        "preimageSha256Lf": preimage,
        "postimageSha256Lf": postimage,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for source, (preimage, postimage) in SOURCES.items()]
