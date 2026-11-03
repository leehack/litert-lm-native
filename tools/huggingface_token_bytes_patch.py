"""Identity and fail-closed application of the HF ByteLevel grammar fix (#100)."""
import hashlib
import re
import subprocess
from pathlib import Path

PATCH_PATH = "native/bridge/huggingface_token_bytes_v019.patch"
AUDITED_TAGS = frozenset({"v0.19.0"})
# LF-normalized upstream v0.19.0 / 83ce6067 preimages and patched postimages.
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
    digests = {name: _digest(source_root / name) for name in SOURCES}
    if all(digests[name] == post for name, (_, post) in SOURCES.items()):
        return
    if any(digests[name] != pre for name, (pre, _) in SOURCES.items()):
        raise RuntimeError("Tokenizer or grammar source changed; requalify #100 token bytes patch")
    patch = Path(__file__).resolve().parents[1] / PATCH_PATH
    command = ["git", "apply", "--ignore-space-change", str(patch)]
    subprocess.run([*command[:2], "--check", *command[2:]], check=True, cwd=source_root)
    subprocess.run(command, check=True, cwd=source_root)
    if any(_digest(source_root / name) != post for name, (_, post) in SOURCES.items()):
        raise RuntimeError("HuggingFace token bytes postimage mismatch; requalify #100")


def token_bytes_patch_manifest(tag: str) -> list[dict]:
    if not require_token_bytes_patch_decision(tag):
        return []
    digest = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / PATCH_PATH).read_bytes()).hexdigest()
    return [{
        "id": "huggingface-token-bytes", "path": PATCH_PATH, "sha256": digest,
        "source": name, "preimageSha256Lf": pre, "postimageSha256Lf": post,
        "scope": "source-built runtimes only; excludes official upstream prebuilts",
    } for name, (pre, post) in SOURCES.items()]
