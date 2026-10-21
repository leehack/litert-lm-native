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
