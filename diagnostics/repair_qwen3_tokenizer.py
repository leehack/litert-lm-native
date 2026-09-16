"""Repair the pinned Qwen3-0.6B bundle with its original HF tokenizer.

This is an explicit, model-specific artifact repair, not a runtime workaround.
The original bundle and tokenizer must match the recorded SHA-256 digests.
Only the tokenizer section and its type/end header fields are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import zlib

MODEL_SHA256 = "555579ff2f4fd13379abe69c1c3ab5200f7338bc92471557f1d6614a6e5ab0b4"
TOKENIZER_SHA256 = "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"
TOKENIZER_URL = (
    "https://huggingface.co/Qwen/Qwen3-0.6B/resolve/"
    "c1899de289a04d12100db370d81485cdf75e47ca/tokenizer.json"
)
# These offsets apply only to MODEL_SHA256, not arbitrary LiteRT-LM containers.
HEADER_SIZE = 32768
TOKENIZER_BEGIN = 32768
TOKENIZER_END = 2681345
TYPE_FIELD = 207
END_FIELD = 208
MODEL_SIZE = 614236160


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def repair(model: Path, tokenizer: Path, output: Path) -> dict[str, str]:
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be a new file; existing files are preserved")
    if sha256(model) != MODEL_SHA256:
        raise ValueError("Model SHA-256 mismatch; this repair supports only the pinned bundle")
    tokenizer_bytes = tokenizer.read_bytes()
    if hashlib.sha256(tokenizer_bytes).hexdigest() != TOKENIZER_SHA256:
        raise ValueError("Tokenizer SHA-256 mismatch; use the pinned original tokenizer")
    payload = struct.pack("<Q", len(tokenizer_bytes)) + zlib.compress(tokenizer_bytes)
    if len(payload) > TOKENIZER_END - TOKENIZER_BEGIN:
        raise ValueError("Compressed tokenizer exceeds the reserved section")
    # Stage beside the destination. Publish exclusively and atomically so a
    # race cannot overwrite another file or expose a partially written model.
    with tempfile.TemporaryDirectory(prefix="qwen-tokenizer-", dir=output.parent) as tmp:
        staged = Path(tmp) / "model.litertlm"
        shutil.copyfile(model, staged)
        if sha256(staged) != MODEL_SHA256:
            raise ValueError("Model changed while preparing repair")
        with staged.open("rb") as source:
            header = bytearray(source.read(HEADER_SIZE))
        if (len(header) != HEADER_SIZE or header[:8] != b"LITERTLM"
                or staged.stat().st_size != MODEL_SIZE or header[TYPE_FIELD] != 4
                or struct.unpack_from("<Q", header, END_FIELD)[0] != TOKENIZER_END):
            raise ValueError("Pinned model layout mismatch")
        header[TYPE_FIELD] = 6  # HF_Tokenizer_Zlib in the upstream schema.
        struct.pack_into("<Q", header, END_FIELD, TOKENIZER_BEGIN + len(payload))
        with staged.open("r+b") as stream:
            stream.write(header)
            stream.seek(TOKENIZER_BEGIN)
            stream.write(payload)
            stream.write(b"\0" * (TOKENIZER_END - TOKENIZER_BEGIN - len(payload)))
        digest = sha256(staged)
        # Hard-link publication is atomic, exclusive, and stays on one filesystem.
        os.link(staged, output)
    return {"model_sha256": MODEL_SHA256, "tokenizer_sha256": TOKENIZER_SHA256,
            "output_sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(repair(args.model, args.tokenizer, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
