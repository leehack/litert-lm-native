"""Identity and fail-closed application of the HF ByteLevel grammar fix (#100)."""
import hashlib
import re
import subprocess
from pathlib import Path

PATCH_PATH = "native/bridge/huggingface_token_bytes_v019.patch"
AUDITED_TAGS = frozenset({"v0.19.0", "v0.19.1", "v0.20.0"})
# LF-normalized upstream v0.19.0 / 83ce6067 preimages and patched postimages;
# v0.19.1 / 7a03724c leaves every preimage unchanged.
SOURCES = {
    "support/tokenizer/tokenizer.h": (
        "f80f9685c276c303bb3110203069ece92bcc61276db537baee50599eed2ad1da",
        "b0ca05aa33fc0a6d7b735806383970e2f24e52d55db6c2bb8192b7123a20ae44",
    ),
    "support/tokenizer/huggingface_tokenizer.h": (
        "f5ef2a52bc703ddc8b1ad620a0e7f92e1f0e4a874cbffdb939eeaa99d3246715",
        "9e38b5f25c0ee9403682e9794f88e03811e74e6c570fe70ce99c5f5ea947f0c5",
    ),
    "support/tokenizer/huggingface_tokenizer.cc": (
        "922ad95701de97e2aedf8514244082d6c1befbced46b8ed59bcc6998d9e985a2",
        "d40a250600d159b25de4b2a5da6afc05695814c8819c3a463616876cb480aa82",
    ),
    "support/tokenizer/BUILD": (
        "91ab9cb6ee4b714140cd5c4bfffd1524d7eb5ae06869f32ad7214cbe5a3cbdef",
        "a38d0653c97324d3e17554e0584ca137775f32e875d8418ae7a0db60be3e5523",
    ),
    "runtime/components/constrained_decoding/llg_constraint_provider.cc": (
        "91e0174e024b8787cdf83b21ca7eaae0718ba140e12f6e7a82bbd6193078e5ce",
        "ce7aef5712d1d3c6eaa632a964f034776aa81216cbdbd8278dec3793bb484159",
    ),
    "runtime/components/constrained_decoding/BUILD": (
        "9ee6588548f9ec54ed1418ff20945e289b60308606bee27e7ad432944b969c04",
        "b16dc8bc86997a7a276c70afc75ad6be1ba70938f31ef4db53bfcc6a9025dd7d",
    ),
}


V020_PATCH_PATH = "native/bridge/huggingface_token_bytes_v020.patch"
V020_SOURCES = {
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


def sources_for(tag: str) -> dict[str, tuple[str, str]]:
    return V020_SOURCES if tag == "v0.20.0" else SOURCES


def patch_path_for(tag: str) -> str:
    return V020_PATCH_PATH if tag == "v0.20.0" else PATCH_PATH


def require_token_bytes_patch_decision(tag: str) -> bool:
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    if version and tuple(map(int, version.groups())) < (0, 19, 0):
        return False
    if tag in AUDITED_TAGS:
        return True
    raise RuntimeError(f"HuggingFace token bytes have no explicit decision for {tag}; "
                       "requalify #100 in docs/upstream_patch_audit.md")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def apply(source_root: Path, tag: str) -> None:
    if not require_token_bytes_patch_decision(tag):
        return
    digests = {name: _digest(source_root / name) for name in sources_for(tag)}
    if all(digests[name] == post for name, (_, post) in sources_for(tag).items()):
        return
    if any(digests[name] != pre for name, (pre, _) in sources_for(tag).items()):
        raise RuntimeError("Tokenizer or grammar source changed; requalify #100 token bytes patch")
    patch = Path(__file__).resolve().parents[1] / patch_path_for(tag)
    command = ["git", "apply", "--ignore-space-change", str(patch)]
    subprocess.run([*command[:2], "--check", *command[2:]], check=True, cwd=source_root)
    subprocess.run(command, check=True, cwd=source_root)
    if any(_digest(source_root / name) != post for name, (_, post) in sources_for(tag).items()):
        raise RuntimeError("HuggingFace token bytes postimage mismatch; requalify #100")


def token_bytes_patch_manifest(tag: str) -> list[dict]:
    if not require_token_bytes_patch_decision(tag):
        return []
    digest = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / patch_path_for(tag)).read_bytes()).hexdigest()
    return [{
        "id": "huggingface-token-bytes", "path": patch_path_for(tag), "sha256": digest,
        "source": name, "preimageSha256Lf": pre, "postimageSha256Lf": post,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for name, (pre, post) in sources_for(tag).items()]
