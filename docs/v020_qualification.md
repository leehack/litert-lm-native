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
| Stream finish reasons | Keep. The upstream C API callback helper still has no cause field. Stop-token, output-budget and context exhaustion still need to reach the bridge separately. |
| Hugging Face grammar | Keep. Upstream adds SentencePiece byte conversion and multiple EOS IDs. The HF path still reads raw vocabulary spellings without ByteLevel inversion and does not provide the JSON whitespace bound or depth guard. |
| Android Qwen3 preflight | Keep. The refactored upstream C API still enters the engine factory directly, without this model and device refusal. |
| Android automatic GPU backend | Select the combined static accelerator and both static samplers independently of the forced-WebGPU flag. Bazel compile actions verify that the LLM, vision and audio executors retain automatic backend selection. |
| Step-zero reset and macOS lookahead | Retire both. Upstream [e1f86b05](https://github.com/google-ai-edge/LiteRT-LM/commit/e1f86b05bf8a731331622a2622440e9f93d9a9f5) clears state on reset, rewind and a new context. On Apple M4 Max, the pinned Qwen3.5-0.8B and Qwen3-0.6B control both passed the packaged step-zero oracle on CPU and Metal with and without the guard. The unguarded Metal run used sampler-managed inputs and matched the fresh reference in all five repeated Qwen3.5 requests. |
| Spatial tensor staging | Rebase the LiteRT WebGPU and Vulkan carry. LiteRT `bf49eb62` predates [aa9e40cd](https://github.com/google-ai-edge/LiteRT/commit/aa9e40cd5e2d892b3a5d8579a7ec6faa696e321e). Retain the pinned LiteRT's per-environment context tracking when staging bindings. |
| XNNPACK PF32 and PQS8/QC4W | Keep both in order. The pinned XNNPACK archive matches all four PF32 preimages, and its PF32-patched `gemm-config.c` matches the QC4W preimage. The original multi-threaded SME2 triggers remain unqualified without the carries. |
| iOS Metal framework path | Retire the dynamic lookup patch for v0.20.0. The upstream registry tries a statically registered GPU accelerator before dynamic lookup. Both iOS arm64 slices from run [45360694287](https://github.com/leehack/litert-lm-native/actions/runs/45360694287) contain `LiteRtStaticLinkedAcceleratorGpuDef` and `GpuMetalAccelerator::CreateDelegate`, link system Metal, and ship no separate accelerator binary. This verifies the linked path and bundle layout. |
| Android Dawn | Keep both checksum-pinned rollback binaries pending Pixel Mali qualification. The validator compares the linked Android runtime's Dawn imports with the final packaged Dawn exports. |
| Windows Android rules repository | Keep. TensorFlow still invokes Bash and `sed` for four repository edits. The native Bazel patch produces the same four files from the pinned archive. |
| Windows C API file descriptor | Keep. The pinned `c/engine.cc` still has a directive inside a macro argument. The carry selects the platform handle before invoking the macro. |
| Earlier retired carries | ASR container routing, the v0.18.1 Bazel repair and CPU options identifier rollback were removed from the current builder. The tag retains the upstream SentencePiece patch and initializes GPU environment options before OpenCL. Historical builds use their recorded native release refs. |


### macOS lookahead retirement evidence

The four runs used Qwen3.5-0.8B `684d4d34…`, the Qwen3-0.6B attention-only
control `c5f39b41…`, and the maintained fresh-process, reload and cancellation
oracle. Guarded dylib `8949b6bfa927e9530ab6a08b9b07ee13b6e282e378c85b78f565f7d9b06d6597`;
unguarded dylib `13eb2161ef4d6dbf5aee6c78b5a6bcd3e649c298b8954161153c7de183ec6341`.
The Metal logs showed executor-managed inputs with the guard and
sampler-managed inputs without it. The attention-only arithmetic control
passed on both builds and backends.

## Runtime and consumer contract

Source builds still link LiteRT in-process. Upstream removed separate LiteRT
and GPU accelerator prebuilts. The desktop and Android packages stage Dawn,
with Windows using `webgpu_dawn.dll`. The Android build selects the combined
GPU accelerator and links both the OpenCL and WebGPU samplers, preserving the
OpenCL probe and the WebGPU fallback when OpenCL is unavailable. The Android
build checks the executor compile actions for a forced WebGPU define and
validates both sampler exports in the resulting library.
The [Android BUILD patch](../native/bridge/android_automatic_gpu_v020.patch)
pins both upstream BUILD files and records their identities in the source
patch inventory.

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

## Text LoRA

The owner probe is ABI 1 and reports support as 0. The pinned Qwen3-0.6B
CPU smoke first creates an ordinary session, then sets a readable temporary
adapter path. The setter returns 0. Session creation returns
`INVALID_ARGUMENT: Lora is not supported.` from the advanced engine's
[resource manager](https://github.com/google-ai-edge/LiteRT-LM/blob/95df4c2a932b4917ace66fcfef6c154e8d2a6699/runtime/framework/resource_management/resource_manager.cc#L616-L635).
This scenario checks executor refusal, independently of audio LoRA support.

PRs run the smoke on the packaged Linux x64, Windows x64, and macOS arm64
runtimes. Release preparation requires it on the same three targets before
packaging. Promoting a prepared candidate requires a successful release
workflow from the same native commit and verifies the candidate digest.
The probe is included in the required bridge exports. The schema-2 manifest
capability keys are unchanged.
