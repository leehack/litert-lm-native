# LiteRT-LM v0.18.0 carried-fix audit

Audited LiteRT-LM `b2f686e2ed4718fb84ec398a61dd59ca0f0aff27`, which pins
LiteRT `26895c9fbcc25c43faa8c1a98cd1fd28951602c3`. Source inspection is
not device or GPU qualification. PR qualification exercises the packaged CPU
paths; affected GPU devices remain separate release-adoption evidence.

| Carried fix | v0.18 decision | Evidence and limit |
| --- | --- | --- |
| GPU environment teardown ordering | Skip for v0.18; retain for supported older inputs | Upstream `GpuEnvironment::Initialize` records options before `InitializeOpenCl`. Existing commit-based selection skips the patch; every Android binary must still pass the disassembly gate. |
| SentencePiece BPE single-NUL compatibility | Keep | WORKSPACE retains SentencePiece 0.2.2 SHA-256 `92381f713e094a15a1ccff1ac4a5315a4c4b82a99ac1332d6ac53c9dc8e1bcf1`, whose unpatched NORMAL NUL rejection breaks the untouched Qwen tokenizer. Sanitizer qualification covers the patched accepted case and malformed variants. |
| iOS Metal accelerator framework path | Keep pending unpatched packaged-device proof | Upstream adds the bare `LiteRtMetalAccelerator` fallback, but the registry still joins it to the runtime directory and loads that path. It does not construct our nested `@executable_path/Frameworks/LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator` path. Preserve the upstream fallback while applying the explicit bundle path. Bazel 7.6.1 patch application passed against both exact old and new source files. |
| iOS Metal sampler framework path | Keep | Upstream `sampler_factory.cc` still requests `libLiteRtTopKMetalSampler.dylib`; our iOS bundle ships `LiteRtTopKMetalSampler.framework/LiteRtTopKMetalSampler`. |
| iOS FST provider disable define | Keep | The upstream gate and provider dependency remain; disabling it preserves our provider-free closure policy. Binary provider/minimum-OS checks remain mandatory; this is not proof of execution on iOS 16.4. |
| zlib download URL workaround | No additional rewrite for v0.18 | Upstream WORKSPACE already supplies the accepted mirror list; the helper preserves it. Retain the older-source URL fallback. |
| Android Dawn rollback | Keep for v0.18 | Stock v0.18 loses the Vulkan device during Qwen inference on Pixel 9 Pro (API 35, Mali-G715). A controlled APK changing only arm64 Dawn to the checksum-pinned historical binary restores raw GPU inference. Extend the existing override to v0.18; this does not fix the separate Galaxy S24 allocation limit or qualify Android x64 hardware. See the linked device qualification record. |
| v0.15 OpenCL sampler override | Inactive for v0.18 | Already restricted to v0.15.0; retain historical build support. |
| Stream finish reasons | Apply only to audited v0.18.0 source hashes (v0.18.1 preimages are identical) | Upstream reports a stop token, the output-token budget and a full context identically, so consumers cannot detect truncation ([#78](https://github.com/leehack/litert-lm-native/issues/78)). See the tracking section below. |
| Untimed ASR overlap alignment | Apply only to audited v0.18.0 source hash (v0.18.1 preimage is identical) | A declarative patch aligns matching boundary words before the word-count fallback. Timed and single-window outputs are unchanged in differential replay; the revised confidence checks prevent the audited periodic collapse and avoid measured clean-corpus regressions, while garbled inputs retain small regressions and repetition gains are reduced. Applies to untimed presets using `TimestampTextMerger` (Moonshine, Whisper tiny, Qwen3-ASR); `tinygemma-asr` uses the Levenshtein merger and is unaffected. See [qualification and retirement gates](asr_untimed_overlap.md) and the [unposted upstream draft](asr_untimed_overlap_upstream_issue.md). Real-model packaged JFK validation remains required. |
| ASR `.litertlm` container routing | Backport to audited v0.18.0 source hashes (v0.18.1 preimages are identical) | Stock v0.18.0 `AsrEngine::Create` sends every `.litertlm` path to the LLM runner, so the published Whisper tiny container (one `tf_lite_encoder_decoder` section plus AsrMetadata and an HF tokenizer) fails with `tf_lite_prefill_decode not found` ([#77](https://github.com/leehack/litert-lm-native/issues/77)). Upstream [`bfdec21732`](https://github.com/google-ai-edge/LiteRT-LM/commit/bfdec21732) selects the decoder from AsrMetadata and loads the container's ASR section and tokenizer; it landed on `main` after the v0.18 branch, and v0.18.1 still lacks it. The backport is that commit's `asr_engine` change without the `kUnspecified` enum. Qwen3-ASR and LLM-only containers keep the LLM route. PR qualification runs the pinned container on CPU plus two derived negatives. |
| v0.18.1 Bazel WORKSPACE build repair | Apply only to audited v0.18.1 WORKSPACE/.bazelrc hashes | v0.18.1 took main's LiteRT `ca21dc99`/TensorFlow `a1179d3c` pin bump without the WORKSPACE plumbing that TensorFlow needs, so Bazel stops in the loading phase: `@rules_cc//cc:extensions.bzl` has no `compatibility_proxy_repo`. `native/bridge/v0181_workspace_build.patch` makes both files byte-identical to upstream main [`d99b438f`](https://github.com/google-ai-edge/LiteRT-LM/commit/d99b438f0a961ac2a449d341c2431e49332c1076), the same change (RevId 996789227) with the same pins: early `bazel_skylib` 1.9.0 and `rules_android` 0.7.2, `bazel_features_deps()`/`compatibility_proxy_repo()` after `tf_workspace3()`, and the MSVC XNNPACK AVX512-BF16 opt-out. It drops only the shadowed first pin assignment; effective pins are unchanged. |
| XNNPACK PF32 SME2 kernel rollback | Apply only to v0.18.1 (TensorFlow `a1179d3c`, XNNPACK `d89ef666`) | XNNPACK [`70a9c5e8ac`](https://github.com/google/XNNPACK/commit/70a9c5e8ac) moved the PF32 SME2 GEMM, GEMV and LHS packing to new KleidiAI kernels that return different f32 results from run to run with more than one thread on SME2 CPUs ([google/XNNPACK#11789](https://github.com/google/XNNPACK/issues/11789), [#82](https://github.com/leehack/litert-lm-native/issues/82)). v0.18.0 pins an XNNPACK from before it. `native/bridge/xnnpack_pf32_sme2.patch` reverts that commit's SME2 kernel wrappers and RHS-packing selection to the previous KleidiAI kernels, which the pinned KleidiAI still ships. The SME (non-SME2) path, other SME2 kernels and non-SME2 CPUs are unchanged. See the tracking section for determinism and speed. |
| XNNPACK SME2 PQS8/QC4W GEMM opt-out | Apply only to v0.18.1 (TensorFlow `a1179d3c`, XNNPACK `d89ef666`), after the PF32 rollback | XNNPACK [`76fa737a0`](https://github.com/google/XNNPACK/commit/76fa737a0b70fa506226b23432633e3781c2a470) sends int8-activation, int4-weight fully connected layers on SME2 CPUs to a packed-LHS path whose only kernel is the 32x32 SME2 MOPA one, so single-token decode runs it at M=1 ([google/XNNPACK#11793](https://github.com/google/XNNPACK/issues/11793), [#84](https://github.com/leehack/litert-lm-native/issues/84)). Gemma 4 E2B CPU decode on Apple M4 drops from about 45 to 30 tok/s. `native/bridge/xnnpack_pqs8_qc4w_sme2.patch` leaves the SME2 `pqs8_qc4w` GEMM config empty, so those layers keep the `qs8_qc4w` kernels v0.18.0 used. Non-SME2 CPUs are unchanged. See the tracking section for speed. |

Primary sources:

- [v0.18 WORKSPACE](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/WORKSPACE)
- [LiteRT GPU environment](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/gpu_environment.cc)
- [LiteRT GPU registry](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/accelerators/gpu_registry.cc)
- [Sampler factory](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/runtime/components/sampler_factory.cc)
- [Android GPU qualification](android_gpu_qualification.md)

## #19 workaround tracking: untimed ASR alignment

The ASR workaround is carried only on the audited v0.18.0 merger preimage.
`upstream.sourcePatches` in schema-2 release manifests records the applied patch
path, SHA-256 and LF-normalized source pre/postimage hashes for source-built
runtimes; official prebuilts are outside that scope. Validators check the record.
This closes this workaround's provenance item, not #19's inventory of all other
source patches. Periodic/repeated-phrase ambiguity and empirical confidence
cutoffs are explicit release risks; the full 5s/30s trade-off table is in the
[qualification report](asr_untimed_overlap.md). Retirement requires an upstream
tagged equivalent, the model-free negative suite and packaged real-model proof.

## #77 workaround tracking: ASR `.litertlm` container routing

`tools/asr_litertlm_container_patch.py` pins the three patched v0.18.0 sources;
any other source fails closed and newer tags need an explicit decision. The
manifest records one `sourcePatches` entry per patched file. Retire the patch
when a tagged upstream release contains `bfdec21732`; upstream `main` has since
replaced `AsrEngine` with the Omni engine, so retirement moves with the bridge's
Omni migration.

## #78 workaround tracking: stream finish reasons

Upstream `ShouldStop` (`runtime/core/tasks.cc`) folds a stop token, the
output-token budget and a full KV cache into `TaskState::kDone`, and the
conversation C API forwards only text, final and error. Step counts cannot
recover the cause: a stop token sampled exactly at the budget step ends with
the same count as a cut-off reply. `native/bridge/stream_finish_reason.patch`
records which `ShouldStop` branch fired, in upstream precedence order, and
carries it through `Conversation` to the final conversation stream chunk.
`stream_proxy_finish_reason_abi_version()` returns 1 only for runtimes built
with the patch; see the [README](../README.md#bridge-finish-reasons).

`tools/stream_finish_reason_patch.py` pins the six patched v0.18.0 sources;
any other source fails closed and newer tags need an explicit decision. The
manifest records one `sourcePatches` entry per patched file. Session-API
streams and Web (`@litert-lm/core`) still report no cause. Retire the patch
when a tagged upstream release exposes an equivalent terminal cause.
`tools/litert_lm_finish_reason_smoke.py` is the opt-in real-model check.

## Stable v0.18.1 candidate

The explicit v0.18.1 carry decisions, dependency/provider delta, full inventory,
source controls and missing binary/device gates are in the
[local qualification report](v0181_qualification.md). No uncertain carry is
retired; the merged #80 finish-reason carry is retained on v0.18.1.

## v0.18.1 WORKSPACE build repair

Stock v0.18.1 does not build with Bazel: the release branch kept the old
`rules_cc` resolution that its own WORKSPACE comment says newer TensorFlow
cannot load. `tools/workspace_build_patch.py` pins the LF pre/postimage hashes
of `WORKSPACE` and `.bazelrc`; the repair runs on the extracted archive before
the owner WORKSPACE edits, and any other source fails closed. The manifest
records one `sourcePatches` entry per file. Retire it when a tagged upstream
release ships an equivalent WORKSPACE.

## #82 workaround tracking: XNNPACK PF32 SME2 kernels

v0.18.1 pins TensorFlow `a1179d3c`, whose XLA pins XNNPACK
`d89ef6669a14db203b3b7935b1b3862cb63fb6df`. That XNNPACK includes
`70a9c5e8ac`, which moved the PF32 SME2 GEMM, GEMV and LHS packing to new
KleidiAI kernels (`f32p4vsx1`). With more than one thread they give run-to-run
different f32 results. On an M4 Max, stock v0.18.1 Qwen3-0.6B greedy CPU chat
differed in 12 of 12 runs and EmbeddingGemma 2 audio embeddings differed
between calls.

`native/bridge/xnnpack_pf32_sme2.patch` reverts that commit in four files: the
`1x32` and `32x32` SME2 wrappers and the SME2 x32 LHS packer call the previous
`f32p2vlx1` KleidiAI kernels again, and the SME2 branch of
`init_pf32_gemm_config` packs weights with `xnn_pack_kai_f32_weights_and_biases_sme`,
the previous packer under its new name. The pinned KleidiAI still ships those
kernels. The commit's other changes (new `_sme2` packer, SME `pack_lh` guards,
tests, benchmarks) stay; the guards leave SME2 CPUs on the same LHS packing
routine v0.18.0 used.

`tools/xnnpack_pf32_sme2_patch.py` declares XLA's exact XNNPACK archive (same
SHA-256, strip prefix and URLs) ahead of `tf_workspace2()`, adding the patch;
XLA's `tf_http_archive` skips a repository that already exists. The WORKSPACE
edit fails closed if the effective TensorFlow pin changes or the WORKSPACE
already declares XNNPACK, and the build fails unless all four sources in
Bazel's `external/XNNPACK` match their pinned postimages. The manifest records
one `sourcePatches` entry per file. The patch applies to every target; it
changes code only on arm64 builds and behavior only on SME2 CPUs.

On an M4 Max at default threads, the rollback is deterministic (Qwen3 chat,
EmbeddingGemma 2 text, image and audio, Gemma 4 E2B text, image and audio) and
runs within 5% of v0.18.0-2 and stock v0.18.1 (median of 9 runs):

| Workload | v0.18.0-2 | Stock v0.18.1 | Rollback |
| --- | ---: | ---: | ---: |
| Qwen3-0.6B prefill / decode (tok/s) | 709 / 32.2 | 696 / 31.7 | 723 / 30.7 |
| EmbeddingGemma 2 image embedding (ms) | 321 | 328 | 325 |
| EmbeddingGemma 2 1 s / 11 s audio embedding (ms) | 76 / 457 | 77 / 451 | 76 / 448 |

Gemma 4 E2B text and image replies are byte-identical to stock v0.18.1, and its
audio transcript matches v0.18.0-2. Disabling the SME2 PF32 config instead
(f32 GEMMs on NEON) was also deterministic but cut Qwen3 prefill about 3x and
doubled image-embedding time. Routing SME2 CPUs to the SME PF32 kernels kept
speed but made image embeddings nondeterministic. Retire the patch when a
tagged upstream release pins an XNNPACK with a fix for google/XNNPACK#11789.

## #84 workaround tracking: XNNPACK SME2 PQS8/QC4W GEMM

XNNPACK `76fa737a0` (google/XNNPACK PR #10986), included in the `d89ef666`
pin, adds a packed-LHS fully connected path for int8 activations with
per-channel int4 weights on SME2 CPUs. It registers only the 32x32 SME2 MOPA
kernel; the 1x64 SME2 DOT kernel for one row exists only as a non-production
kernel (`NON_PROD_NEONSME2_MICROKERNEL_SRCS`), so production builds do not
compile it. Gemma
4 E2B's int4 layers therefore decode one token at a time through a 32-row
tile, which stops scaling beyond about four threads on Apple M4, instead of
v0.18.0's NEON `qs8_qc4w` 1x16c4 kernel.

`native/bridge/xnnpack_pqs8_qc4w_sme2.patch` gates off the SME2 branch of
`init_pqs8_qc4w_gemm_config`, so `xnn_init_pqs8_qc4w_gemm_config()` returns
NULL and XNNPACK's subgraph keeps the unpacked `qs8_qc4w` path. It is the second
patch on the XNNPACK archive declared for #82, applied after
`xnnpack_pf32_sme2.patch`; its `gemm-config.c` preimage is that patch's
postimage. The build checks the final postimage of every patched XNNPACK source,
and the manifest records one `sourcePatches` entry after the PF32 entries.

On an M4 Max at default threads (median of 9 runs over 3 interleaved rounds):

| Gemma 4 E2B CPU, tok/s | v0.18.0-3 | v0.18.1 with the PF32 rollback | Plus this opt-out |
| --- | ---: | ---: | ---: |
| Text prefill / decode | 594 / 44.9 | 684 / 29.9 | 582 / 46.8 |
| Image prompt decode | 45.8 | 30.3 | 46.5 |
| Audio prompt decode | 46.0 | 30.2 | 46.4 |

Gemma 4 and Qwen3 replies and EmbeddingGemma 2 vectors are byte-identical with
and without the opt-out and stay deterministic; Metal GPU decode is unchanged.
The opt-out gives back the path's prefill gain: about 15% at default threads and
3-4% at eight threads, but about 42-44% at one or two threads (293 to 172 and
525 to 292 tok/s on M4 Max). SME2 phones running few threads were not measured. Retire the patch when a tagged upstream release pins an
XNNPACK that registers a single-row kernel or otherwise fixes
google/XNNPACK#11793, verified on multithreaded SME2 decode.
