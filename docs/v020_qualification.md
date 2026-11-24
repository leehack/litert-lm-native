# LiteRT-LM v0.20.0 qualification

PR builds use [LiteRT-LM v0.20.0](https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.20.0)
at `95df4c2a932b4917ace66fcfef6c154e8d2a6699`. Its `WORKSPACE` pins LiteRT
`bf49eb62406d15948261a840c9dcd8e4f13b478c`, TensorFlow
`faa06da43657488c1f7479289d11d15e03a15ba1` and ML Drift
`e9229fa80c4a99f1855721aec8282f7f4ce86fe4`. TensorFlow pins XNNPACK
`08cc38b61f7589f84e91c6e343e0f130ae3279ca`. The build verifies the declared
archive identities, Bazel repository tree hashes and patched postimages.

## Carry decisions

| Carry | v0.20.0 decision |
| --- | --- |
| ASR overlap | Keep the v0.19 patch and pin the new preimage and postimage. The merger's text-utils include moved to `omni/utils`. |
| Stream finish reasons | Rebase onto the shared C API callback helper and the new multi-token decode loop. Keep the finish-reason wire values and bridge ABI. |
| Hugging Face grammar | Rebase on the thread-safe tokenizer and LLGuidance v2. Keep exact ByteLevel bytes, the JSON whitespace bound and depth guard. Preserve upstream SentencePiece byte conversion and multiple EOS IDs. |
| Android Qwen3 preflight | Rebase onto the refactored engine factory. The refusal still runs before factory entry. |
| Step-zero reset and macOS lookahead | Upstream [e1f86b05](https://github.com/google-ai-edge/LiteRT-LM/commit/e1f86b05bf8a731331622a2622440e9f93d9a9f5) supplies state clearing on reset, rewind and a new context. The v0.20 carry contains only the macOS WebGPU linear-attention guard. |
| Spatial tensor staging | Rebase the LiteRT WebGPU and Vulkan carry. LiteRT `bf49eb62` predates [aa9e40cd](https://github.com/google-ai-edge/LiteRT/commit/aa9e40cd5e2d892b3a5d8579a7ec6faa696e321e). Retain the pinned LiteRT's per-environment context tracking when staging bindings. |
| XNNPACK PF32 and PQS8/QC4W | Both patches apply in their existing order to the new pin. Update the `gemm-config.c` hashes. |
| iOS Metal framework path | Rebase the legacy path carry. The default build links the accelerator statically. Retiring the path carry still requires packaged iOS evidence. |
| Android Dawn | Keep both checksum-pinned rollback binaries pending Pixel Mali qualification. The validator compares the linked Android runtime's Dawn imports with the final packaged Dawn exports. |
| Earlier retired carries | ASR container routing, the v0.18.1 Bazel repair and CPU options identifier rollback stay inactive. The tag retains the upstream SentencePiece patch and initializes GPU environment options before OpenCL. |

## Runtime and consumer contract

Source builds still link LiteRT in-process. Upstream removed separate LiteRT
and GPU accelerator prebuilts. The desktop and Android packages stage Dawn,
with Windows using `webgpu_dawn.dll`. The Android build selects the combined
GPU accelerator and links both the OpenCL and WebGPU samplers, preserving the
fallback when OpenCL is unavailable.

The C API version is `1.1.0`. The existing stable status/out-parameter signatures
are preserved. New APIs include selected signatures, tool choice and ModelSync.
The experimental debugger query was replaced by an engine setting. Existing
llamadart bindings can keep their stable signatures once the ABI loader admits
1.1.x. Pin synchronizers must admit the new compatibility tag, Dawn overrides
and runtime inventory. The SwiftPM companion release must match the new runtime
line.

The NPU executor now reads unset handwritten-component flags from bundle
metadata. Without a flag in the bundle or runtime options, those components are
disabled except for the ring-buffer KV-cache update case. The benchmark
`totalInitTime` now reports engine creation time. See the
[upstream release notes](https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.20.0).

The full PR qualification matrix builds all eight runtimes and checks packaged
CPU ASR, Qwen inference and C ABI on Linux x64, Windows x64 and macOS arm64.
Android device behavior, iOS device execution and Metal inference require
separate qualification.
