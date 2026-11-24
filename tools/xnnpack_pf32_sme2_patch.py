"""Identity of the carried XNNPACK PF32 SME2 kernel rollback (#82)."""
import hashlib
import re
from pathlib import Path

from source_patch_utils import active_source_carries

PATCH_PATH = "native/bridge/xnnpack_pf32_sme2.patch"
# The PF32 SME2 kernels introduced here are nondeterministic with multiple
# threads (google/XNNPACK#11789).
REVERTED_COMMIT = "70a9c5e8acf90bef0c56f33a14529027585fd436"
TENSORFLOW_REF = "faa06da43657488c1f7479289d11d15e03a15ba1"
XNNPACK_COMMIT = "08cc38b61f7589f84e91c6e343e0f130ae3279ca"
XNNPACK_SHA256 = "1c94d80ff3069b3510e54b41a2c82729a4053724a682fcb09840af296dcaa07c"
XNNPACK_URL = f"https://github.com/google/XNNPACK/archive/{XNNPACK_COMMIT}.zip"
SOURCES = {
    "src/configs/gemm-config.c": (
        "77f6499beb82d69ca19dd9ca31a7c591b07c78863c158701b1125dcee0bb843d",
        "0eff752814ec351176c48461832907ab8841c81d06c330483dae1cf45d233a9c",
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


def archive(tensorflow_ref: str, commit: str, sha256: str) -> str:
    # Declared ahead of tf_workspace2(): XLA's tf_http_archive skips a repository
    # that already exists, so this exact archive is the one every target links.
    # Patches apply in order; the PQS8/QC4W opt-out (#84) edits the PF32 postimage
    # of src/configs/gemm-config.c.
    url = f"https://github.com/google/XNNPACK/archive/{commit}.zip"
    return f'''# XNNPACK pinned by TensorFlow {tensorflow_ref[:8]} (XLA third_party/xnnpack),
# with the PF32 SME2 kernels of {REVERTED_COMMIT[:10]} reverted (litert-lm-native#82)
# and the SME2 PQS8/QC4W GEMM config disabled (litert-lm-native#84).
http_archive(
    name = "XNNPACK",
    patch_args = ["-p1"],
    patches = [
        "@//bridge:xnnpack_pf32_sme2.patch",
        "@//bridge:xnnpack_pqs8_qc4w_sme2.patch",
    ],
    sha256 = "{sha256}",
    strip_prefix = "XNNPACK-{commit}",
    urls = [
        "https://storage.googleapis.com/mirror.tensorflow.org/{url[8:]}",
        "{url}",
    ],
)

'''


ARCHIVE = archive(TENSORFLOW_REF, XNNPACK_COMMIT, XNNPACK_SHA256)


TENSORFLOW_ARCHIVE = '# TensorFlow\nhttp_archive(\n    name = "org_tensorflow",\n'


def verify_patched_xnnpack_archive(workspace: str, compatibility_tag: str) -> None:
    if not active_source_carries(compatibility_tag):
        raise RuntimeError(f"XNNPACK carries are unavailable for {compatibility_tag}; use its historical release ref")
    if (workspace.count(ARCHIVE + TENSORFLOW_ARCHIVE) != 1
            or len(re.findall(r'^\s*name = "XNNPACK",$', workspace, re.MULTILINE)) != 1):
        raise RuntimeError("Unexpected XNNPACK archive in WORKSPACE; requalify the XNNPACK patches")


def declare_patched_xnnpack(workspace_text: str) -> str:
    """Inserts the patched XNNPACK archive before the TensorFlow archive."""
    refs = re.findall(r'^TENSORFLOW_REF = "([0-9a-f]{40})"$', workspace_text, re.MULTILINE)
    # Starlark uses the last assignment.
    if not refs or refs[-1] != TENSORFLOW_REF:
        raise RuntimeError("TensorFlow pin changed; requalify the XNNPACK patches")
    if ARCHIVE in workspace_text:
        return workspace_text
    if re.search(r'^\s*name = "XNNPACK",$', workspace_text, re.MULTILINE):
        raise RuntimeError("Unexpected XNNPACK archive in WORKSPACE; requalify the XNNPACK patches")
    if workspace_text.count(TENSORFLOW_ARCHIVE) != 1:
        raise RuntimeError("Expected one TensorFlow archive in WORKSPACE")
    return workspace_text.replace(TENSORFLOW_ARCHIVE, ARCHIVE + TENSORFLOW_ARCHIVE, 1)


def xnnpack_pf32_patch_manifest(compatibility_tag: str) -> list[dict]:
    if not active_source_carries(compatibility_tag):
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
