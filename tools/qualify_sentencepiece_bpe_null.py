#!/usr/bin/env python3
"""Compile the audited tokenizer patch and preserve Qwen's legacy token semantics."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import subprocess
import tarfile

from download_utils import download_to_path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "92381f713e094a15a1ccff1ac4a5315a4c4b82a99ac1332d6ac53c9dc8e1bcf1"
MODEL_SHA = "555579ff2f4fd13379abe69c1c3ab5200f7338bc92471557f1d6614a6e5ab0b4"
TOKENIZER_SHA = "8303cd8554b5b05ca65bdac55d601ae7cff0106a27055511112dc46c13bec9d8"
MODEL_URL = "https://huggingface.co/litert-community/Qwen3-0.6B/resolve/main/Qwen3-0.6B.litertlm?download=true"


def verified_download(url: str, path: Path, expected: str) -> None:
    if not path.exists():
        download_to_path(url, path, headers={"User-Agent": "litert-lm-native-qualification"}, label=path.name, expected_sha256=expected)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise RuntimeError(f"Checksum mismatch: {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    archive = work / "sentencepiece-0.2.2.tar.gz"
    verified_download("https://github.com/google/sentencepiece/archive/refs/tags/v0.2.2.tar.gz", archive, SOURCE_SHA)
    model = work / "Qwen3-0.6B.litertlm"
    verified_download(MODEL_URL, model, MODEL_SHA)
    with model.open("rb") as stream:
        stream.seek(32768)
        tokenizer = stream.read(2681345 - 32768)
    if hashlib.sha256(tokenizer).hexdigest() != TOKENIZER_SHA:
        raise RuntimeError("Pinned Qwen tokenizer section mismatch")
    tokenizer_path = work / "qwen-tokenizer.model"
    tokenizer_path.write_bytes(tokenizer)
    source = work / "sentencepiece-0.2.2"
    if source.exists():
        raise RuntimeError("Use a fresh qualification work directory")
    with tarfile.open(archive) as stream:
        stream.extractall(work, filter="data")
    def run(command: list[str]) -> None:
        subprocess.run(command, cwd=source, check=True)
    # Reproduce the original failure first, so a passing test cannot hide a bad fixture.
    configure = ["cmake", "-S", ".", "-B", "build", "-DSPM_BUILD_TEST=ON", "-DSPM_ENABLE_SHARED=OFF", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"]
    if args.sanitize:
        configure += ["-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined -fno-omit-frame-pointer", "-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined"]
    run(configure)
    run(["cmake", "--build", "build", "--target", "spm_encode", "-j", "3"])
    baseline = subprocess.run([str(source / "build/src/spm_encode"), f"--model={tokenizer_path}"], input="", text=True, capture_output=True)
    if baseline.returncode == 0 or "piece must not include null character" not in baseline.stderr:
        raise RuntimeError("Unpatched tokenizer did not reproduce the expected failure")
    run(["patch", "-p1", "-i", str(ROOT / "native/bridge/sentencepiece_bpe_null.patch")])
    (source / "src/qwen_null_test.cc").write_text((ROOT / "tests/sentencepiece_bpe_null_test.cc").read_text())
    with (source / "src/CMakeLists.txt").open("a") as stream:
        stream.write("\nadd_executable(qwen_null_test qwen_null_test.cc)\ntarget_link_libraries(qwen_null_test sentencepiece)\n")
    run(configure)
    run(["cmake", "--build", "build", "-j", "3"])
    run(["ctest", "--test-dir", "build", "--output-on-failure"])
    result = subprocess.run([str(source / "build/src/qwen_null_test"), str(tokenizer_path)], check=True, text=True, capture_output=True)
    if result.stdout != (ROOT / "tests/sentencepiece_qwen_expected.txt").read_text():
        raise RuntimeError("Token IDs or decoded bytes differ from SentencePiece 0.2.0")
    print(result.stderr.strip())


if __name__ == "__main__":
    main()
