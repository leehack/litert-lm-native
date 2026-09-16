# Qwen3 byte-level tokenizer repair

Native issue [#48](https://github.com/leehack/litert-lm-native/issues/48) is a
model-conversion defect in the pinned `litert-community/Qwen3-0.6B` bundle.
Its SentencePiece vocabulary contains decoded complete UTF-8 tokens mixed with
literal byte-level BPE spellings for incomplete UTF-8 tokens. For example,
original Qwen IDs `[9707, 0, 26525, 232]` should decode to `Hello! 😊`; the
converted tokenizer produces `Hello!ĠðŁĺĬ`. An encode/decode round trip alone
misses this because the converted tokenizer may encode an emoji using a
different, complete token. The upstream conversion utility documents that its
SentencePiece conversion is heuristic and not token-ID equivalent for all input.

The existing v0.17.0-3 runtime already supports original Hugging Face tokenizer
sections. Use the explicit repair below to create a new model file with the
original tokenizer JSON, preserving all tensor weights, other sections, and
original token IDs. It does not modify runtime binaries, the source model,
consumer downloads, or output strings. It does not generalize to other models.

## Inputs

- Model: `litert-community/Qwen3-0.6B`, revision
  `8414150f2e9dcc82449bcc9c5abc404b399a4d06`, `Qwen3-0.6B.litertlm`.
  SHA-256: `555579ff2f4fd13379abe69c1c3ab5200f7338bc92471557f1d6614a6e5ab0b4`.
- Original tokenizer: [Qwen/Qwen3-0.6B tokenizer.json](https://huggingface.co/Qwen/Qwen3-0.6B/resolve/c1899de289a04d12100db370d81485cdf75e47ca/tokenizer.json).
  SHA-256: `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4`.

Download those exact inputs, then run with Python 3.11+:

```sh
python3 diagnostics/repair_qwen3_tokenizer.py \
  --model /path/to/Qwen3-0.6B.litertlm \
  --tokenizer /path/to/tokenizer.json \
  --output /path/to/Qwen3-0.6B-repaired.litertlm
python3 -m unittest discover -s diagnostics -p 'test_*.py'
```

The tool rejects unknown input hashes, changed layout, and existing outputs.
It stores the original JSON as the upstream `HF_Tokenizer_Zlib` section,
updates only its header type/end fields, and zero-fills unused tokenizer space.
The new file is published atomically without replacing existing files. Keep the
original bundle for comparison. The tool prints input and output hashes for
provenance; compressed bytes can vary with the host zlib implementation.

## Qualification

On macOS arm64 with v0.17.0-3, the repaired bundle produces `Hello! 😊` through
native CPU chat. Plain response, thinking plus final answer, and system/history
recall pass the maintained llamadart chat smoke. Original-tokenizer reference
cases cover French, Chinese, Korean, Arabic, Japanese, whitespace, literal BPE
characters, normalization, and split emoji tokens. Compare normalized text to
the original tokenizer's decoder, not necessarily the unnormalized input.
The C string API cannot round-trip embedded NUL; this repair does not change
that interface limitation or the existing SentencePiece NUL compatibility guard.

GPU availability is separate from tokenizer correctness. This repair does not
remove the Linux/Windows GPU gate or fix native issue #47. Android, iOS, and
Windows/Linux model-backed qualification of the repaired bundle are not claimed
by the macOS evidence. Consumer model catalogs continue to download the original
bundle until a separately qualified replacement is published and adopted.
