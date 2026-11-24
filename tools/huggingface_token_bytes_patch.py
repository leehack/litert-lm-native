"""Identity and fail-closed application of the HF ByteLevel grammar fix (#100)."""
import hashlib
from pathlib import Path

from source_patch_utils import active_source_carries, apply_source_patch

PATCH_PATH = "native/bridge/huggingface_token_bytes_v020.patch"
SOURCES = {
    "runtime/components/constrained_decoding/BUILD": (
        "dfce389070058c835975ca2f76d4858830156928b12131c53a5933cb522661f8",
        "a73f1ba0602ed08e6b6c63042be557fed3a6d1815d92cf588d96a8d14cde4b6b",
    ),
    "runtime/components/constrained_decoding/llg_constraint_provider.cc": (
        "793ec01ba12f7b0a4ae6d5ba75ab226ec064d5aaff3fdde7698115f927ca3122",
        "722aaa0e0204e74ecf56bbd9675d59be3b6537d944074236606c279421a69e2d",
    ),
    "support/tokenizer/BUILD": (
        "8d7f0fb096e24f468057dd4a4d276962e898693857dedb0743805be388117610",
        "117ab89ab377a2067b34f8ea84a9fdc2d054d0b3303a49c85f24ff3542660c01",
    ),
    "support/tokenizer/huggingface_tokenizer.cc": (
        "ec69b3dff009ede39d82c1d280d859530cc3cc598b36a9c8cc94d986adf24c20",
        "5853d97e37a62957331db217c9f5e4a2f5ef89e725f5417aac350232505edad6",
    ),
    "support/tokenizer/huggingface_tokenizer.h": (
        "b9c723c1314869d347a119378a978612f48ac6575317ca0aad41a3dabbacf74a",
        "5623e1a7fe0e8723fca39c7902dd2b7a8b5f4f846a7e53b88b078e8c36a5d7cd",
    ),
    "support/tokenizer/tokenizer.h": (
        "f80f9685c276c303bb3110203069ece92bcc61276db537baee50599eed2ad1da",
        "b0ca05aa33fc0a6d7b735806383970e2f24e52d55db6c2bb8192b7123a20ae44",
    ),
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def apply(source_root: Path, tag: str) -> None:
    if not active_source_carries(tag):
        return
    sources = SOURCES
    digests = {name: _digest(source_root / name) for name in sources}
    if all(digests[name] == post for name, (_, post) in sources.items()):
        return
    if any(digests[name] != pre for name, (pre, _) in sources.items()):
        raise RuntimeError("Tokenizer or grammar source changed; requalify #100 token bytes patch")
    patch = Path(__file__).resolve().parents[1] / PATCH_PATH
    apply_source_patch(source_root, patch, ignore_space_change=True)
    mismatches = [name for name, (_, post) in sources.items()
                  if _digest(source_root / name) != post]
    if mismatches:
        raise RuntimeError(
            f"HuggingFace token bytes postimage mismatch for {', '.join(mismatches)}; "
            "requalify #100")


def token_bytes_patch_manifest(tag: str) -> list[dict]:
    if not active_source_carries(tag):
        return []
    digest = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest()
    return [{
        "id": "huggingface-token-bytes", "path": PATCH_PATH, "sha256": digest,
        "source": name, "preimageSha256Lf": pre, "postimageSha256Lf": post,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for name, (pre, post) in SOURCES.items()]
